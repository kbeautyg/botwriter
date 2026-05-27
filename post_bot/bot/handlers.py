"""aiogram handlers: вся логика бота."""
from __future__ import annotations

from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from post_bot.bot import messages as M
from post_bot.bot.keyboards import (
    after_rating_kb,
    brief_collecting_kb,
    rating_kb,
)
from post_bot.bot.states import BriefStates
from post_bot.config import get_settings
from post_bot.db.engine import get_session
from post_bot.db.models import Brief, Post
from post_bot.db.repository import (
    append_text,
    append_voice,
    create_brief,
    get_brief,
    rate_post,
    set_brief_status,
)
from post_bot.llm.stt import transcribe
from post_bot.pipeline.orchestrator import generate_post, save_post_as_example
from post_bot.utils.logger import logger

router = Router(name="post-bot")


# ----------------------------- /start -----------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(M.START)


# ----------------------------- /new -----------------------------

@router.message(Command("new"))
@router.callback_query(F.data == "brief:new")
async def cmd_new(event: Message | CallbackQuery, state: FSMContext) -> None:
    user_id = event.from_user.id  # type: ignore[union-attr]
    msg = event if isinstance(event, Message) else event.message

    current_state = await state.get_state()
    if current_state == BriefStates.waiting.state:
        if isinstance(event, CallbackQuery):
            await event.answer()
        await msg.answer(M.ALREADY_COLLECTING)  # type: ignore[union-attr]
        return

    async with get_session() as s:
        brief = await create_brief(s, user_id)
        brief_id = brief.id

    await state.clear()
    await state.set_state(BriefStates.waiting)
    await state.update_data(brief_id=brief_id)

    if isinstance(event, CallbackQuery):
        await event.answer()
    await msg.answer(M.NEW_BRIEF, reply_markup=brief_collecting_kb())  # type: ignore[union-attr]


# ----------------------------- /cancel -----------------------------

@router.message(Command("cancel"))
@router.callback_query(F.data == "brief:cancel")
async def cmd_cancel(event: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    brief_id = data.get("brief_id")
    if brief_id:
        async with get_session() as s:
            brief = await get_brief(s, brief_id)
            if brief and brief.status == "collecting":
                await set_brief_status(s, brief, "cancelled")
    await state.clear()
    msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
    await msg.answer(M.CANCELLED)  # type: ignore[union-attr]


# ----------------------------- /done -----------------------------

@router.message(Command("done"))
@router.callback_query(F.data == "brief:generate")
async def cmd_done(event: Message | CallbackQuery, state: FSMContext, bot: Bot) -> None:
    current_state = await state.get_state()
    if current_state != BriefStates.waiting.state:
        msg = event if isinstance(event, Message) else event.message
        if isinstance(event, CallbackQuery):
            await event.answer()
        await msg.answer(M.NOT_IN_BRIEF)  # type: ignore[union-attr]
        return

    data = await state.get_data()
    brief_id: int = data["brief_id"]

    async with get_session() as s:
        brief = await get_brief(s, brief_id)
        if brief is None or not brief.combined_input.strip():
            await state.clear()
            msg = event if isinstance(event, Message) else event.message
            if isinstance(event, CallbackQuery):
                await event.answer()
            await msg.answer(M.EMPTY_BRIEF)  # type: ignore[union-attr]
            return

    await state.set_state(BriefStates.generating)
    msg = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
    status_msg = await msg.answer(M.GENERATING)  # type: ignore[union-attr]

    try:
        result = await generate_post(brief_id)
    except Exception as e:
        logger.exception("Pipeline failed")
        await status_msg.edit_text(M.ERROR_GENERIC.format(err=e))
        await state.clear()
        return

    await state.set_state(BriefStates.awaiting_rating)
    await state.update_data(post_id=result.post.id)
    await status_msg.delete()

    # Заголовок — отдельным сообщением (короткий)
    await msg.answer(  # type: ignore[union-attr]
        M.render_post_header(
            score=result.final_score,
            iterations=result.iterations,
            genre=result.post.genre,
        )
    )
    # Сам пост — отдельным, без parse_mode (чтобы символы * _ не сломали разметку)
    await msg.answer(result.final_draft.text)  # type: ignore[union-attr]
    # Кнопки оценки — третьим
    await msg.answer(  # type: ignore[union-attr]
        M.render_rating_prompt(),
        reply_markup=rating_kb(result.post.id),
    )


# ----------------------------- /history -----------------------------

@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    async with get_session() as s:
        stmt = (
            select(Post)
            .order_by(Post.created_at.desc())
            .limit(5)
        )
        rows = (await s.execute(stmt)).scalars().all()
    out = M.render_history([
        (p.id, p.genre or "—", p.user_rating, (p.text[:80] + ("…" if len(p.text) > 80 else "")))
        for p in rows
    ])
    await message.answer(out)


# ----------------------------- сбор брифа -----------------------------

@router.message(BriefStates.waiting, F.voice)
@router.message(BriefStates.waiting, F.audio)
async def on_voice(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    brief_id: int = data["brief_id"]

    voice = message.voice or message.audio
    if voice is None:
        return

    await message.answer(M.VOICE_RECEIVED)

    try:
        buf = BytesIO()
        await bot.download(voice, destination=buf)
        audio_bytes = buf.getvalue()
        filename = "voice.ogg" if message.voice else (voice.file_name or "audio.mp3")
        text = await transcribe(audio_bytes, filename=filename)
    except Exception as e:
        logger.exception("Voice transcription failed")
        await message.answer(M.VOICE_FAILED.format(err=e))
        return

    if not text.strip():
        await message.answer(M.VOICE_FAILED.format(err="пустая расшифровка"))
        return

    async with get_session() as s:
        brief = await get_brief(s, brief_id)
        if brief is None:
            return
        await append_voice(s, brief, text)

    preview = (text[:120] + "…") if len(text) > 120 else text
    await message.answer(
        M.VOICE_TRANSCRIBED.format(preview=preview),
        reply_markup=brief_collecting_kb(),
    )


@router.message(BriefStates.waiting, F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/"):
        return  # это команда, обработают другие handlers
    data = await state.get_data()
    brief_id: int = data["brief_id"]
    txt = (message.text or "").strip()
    if not txt:
        return
    async with get_session() as s:
        brief = await get_brief(s, brief_id)
        if brief is None:
            return
        await append_text(s, brief, txt)
    await message.answer(
        M.TEXT_RECEIVED.format(n_chars=len(txt)),
        reply_markup=brief_collecting_kb(),
    )


# ----------------------------- оценка поста -----------------------------

@router.callback_query(F.data.startswith("rate:"))
async def on_rate(cb: CallbackQuery, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 3:
        await cb.answer()
        return
    _, post_id_s, rating_s = parts
    post_id = int(post_id_s)
    rating = int(rating_s)

    s_cfg = get_settings()
    saved = False
    async with get_session() as session:
        post = await session.get(Post, post_id)
        if post is None:
            await cb.answer("Пост не найден", show_alert=True)
            return
        await rate_post(session, post, rating=rating)

    if rating >= s_cfg.auto_save_as_example_threshold:
        await save_post_as_example(post_id, score=rating)
        saved = True

    await cb.answer("Записал")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=after_rating_kb())
        await cb.message.answer(M.render_rating_saved(rating, saved))


@router.callback_query(F.data.startswith("save:"))
async def on_save(cb: CallbackQuery) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 2:
        await cb.answer()
        return
    post_id = int(parts[1])

    s_cfg = get_settings()
    async with get_session() as session:
        post = await session.get(Post, post_id)
        if post is None:
            await cb.answer("Пост не найден", show_alert=True)
            return
        # Если рейтинга нет — присваиваем порог автосохранения (минимальный для "достоин примера").
        score = post.user_rating if post.user_rating is not None else s_cfg.auto_save_as_example_threshold

    await save_post_as_example(post_id, score=score)
    await cb.answer("Сохранил в базу примеров")
    if cb.message:
        await cb.message.answer("💾 Пост ушёл в базу примеров.")


# ----------------------------- редактура (post awaiting_rating) -----------------------------

@router.message(BriefStates.awaiting_rating, F.text)
async def on_edit_after_rating(message: Message, state: FSMContext) -> None:
    """Если юзер прислал текст в состоянии awaiting_rating — считаем это правкой."""
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        return
    edited = (message.text or "").strip()
    if not edited:
        return
    async with get_session() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return
        post.edited_text = edited
    await message.answer("📝 Правка сохранена. Не забудь поставить оценку финального варианта.")

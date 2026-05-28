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
    GENRES_RU,
    after_rating_kb,
    back_to_menu_kb,
    brief_collecting_kb,
    confirm_delete_directive_kb,
    directive_genre_kb,
    directive_polarity_kb,
    directives_list_kb,
    genre_choice_kb,
    length_choice_kb,
    main_menu_kb,
    rating_kb,
    score_choice_kb,
)
from post_bot.bot.states import BriefStates, DirectiveStates, ExampleStates
from post_bot.config import get_settings
from post_bot.db.engine import get_session
from post_bot.db.models import Post, UserDirective
from post_bot.db.repository import (
    add_good_phrase,
    add_style_example,
    add_user_directive,
    append_text,
    append_voice,
    create_brief,
    deactivate_directive,
    get_brief,
    list_all_directives,
    rate_post,
    set_brief_status,
)
from post_bot.llm.feedback_extractor import extract_directives
from post_bot.llm.stt import transcribe
from post_bot.llm.stylist import extract_style
from post_bot.pipeline.orchestrator import generate_post, save_post_as_example
from post_bot.utils.logger import logger

_GENRE_LABELS = {code: label for code, label in GENRES_RU}

router = Router(name="post-bot")


# ----------------------------- /start и главное меню -----------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(M.START, reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:home")
async def on_menu_home(cb: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню из любого экрана."""
    await state.clear()
    await cb.answer()
    if cb.message:
        await cb.message.answer(M.MENU_HOME, reply_markup=main_menu_kb())


# ----------------------------- /new -----------------------------

@router.message(Command("new"))
@router.callback_query(F.data == "brief:new")
@router.callback_query(F.data == "menu:new")
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
    await state.set_state(BriefStates.choosing_length)
    await state.update_data(brief_id=brief_id)

    if isinstance(event, CallbackQuery):
        await event.answer()
    await msg.answer(M.LENGTH_PROMPT, reply_markup=length_choice_kb())  # type: ignore[union-attr]


# ----------------------------- выбор длины -----------------------------

@router.callback_query(F.data.startswith("length:"))
async def on_length_choice(cb: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != BriefStates.choosing_length.state:
        await cb.answer()
        return
    parts = (cb.data or "").split(":")
    if len(parts) != 2:
        await cb.answer()
        return
    value = parts[1]
    target: int | None
    label: str
    if value == "auto":
        target = None
        label = "Авто"
    else:
        try:
            target = int(value)
        except ValueError:
            target = None
            label = "Авто"
        else:
            label = f"~{target} слов"

    data = await state.get_data()
    brief_id = data.get("brief_id")
    if brief_id:
        async with get_session() as s:
            brief = await get_brief(s, brief_id)
            if brief:
                brief.target_length_words = target

    await state.set_state(BriefStates.waiting)
    await cb.answer()
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(
            M.NEW_BRIEF_AFTER_LENGTH.format(length_label=label),
            reply_markup=brief_collecting_kb(),
        )


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

    final_text = (result.final_draft.text or "").strip()
    if not final_text:
        # Все итерации пустые — модель не справилась (обычно gpt-5.x + reasoning).
        await msg.answer(  # type: ignore[union-attr]
            "⚠️ Не получилось собрать черновик: модель вернула пустой ответ. "
            "Попробуй ещё раз через /new — иногда reasoning-модели «зависают». "
            "Если повторяется — смени MODEL_WRITER на gpt-4o в Variables на Railway."
        )
        await state.clear()
        return

    # Заголовок — отдельным сообщением (короткий)
    await msg.answer(  # type: ignore[union-attr]
        M.render_post_header(
            score=result.final_score,
            iterations=result.iterations,
            genre=result.post.genre,
        )
    )
    # Сам пост — отдельным, без parse_mode (чтобы символы * _ не сломали разметку)
    await msg.answer(final_text)  # type: ignore[union-attr]
    # Кнопки оценки — третьим
    await msg.answer(  # type: ignore[union-attr]
        M.render_rating_prompt(),
        reply_markup=rating_kb(result.post.id),
    )


# ----------------------------- /history -----------------------------

async def _send_history(send) -> None:
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
    await send(out, reply_markup=back_to_menu_kb())


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    await _send_history(message.answer)


@router.callback_query(F.data == "menu:history")
async def on_menu_history(cb: CallbackQuery) -> None:
    await cb.answer()
    if cb.message:
        await _send_history(cb.message.answer)


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


# ----------------------------- комментарий к посту -----------------------------

@router.callback_query(F.data.startswith("comment:"))
async def on_comment_button(cb: CallbackQuery, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 2:
        await cb.answer()
        return
    post_id = int(parts[1])
    await state.set_state(BriefStates.awaiting_comment)
    await state.update_data(comment_post_id=post_id)
    await cb.answer()
    if cb.message:
        await cb.message.answer(M.COMMENT_PROMPT)


@router.message(BriefStates.awaiting_comment, F.text)
async def on_comment_text(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    post_id = data.get("comment_post_id")
    comment = (message.text or "").strip()
    if not post_id or not comment:
        return

    # сохранить как user_note
    async with get_session() as session:
        post = await session.get(Post, post_id)
        if post:
            existing = post.user_note or ""
            post.user_note = (existing + "\n" + comment).strip() if existing else comment

    # извлечь директивы
    extracted = None
    try:
        extracted = await extract_directives(comment)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Directive extraction failed: {e}")

    saved_count = 0
    if extracted and extracted.directives:
        async with get_session() as session:
            for d in extracted.directives:
                await add_user_directive(
                    session,
                    text=d.text,
                    polarity=d.polarity,
                    genre_scope=d.genre_scope,
                    source_post_id=post_id,
                    raw_comment=comment,
                )
                saved_count += 1

    await state.set_state(BriefStates.awaiting_rating)
    if saved_count and extracted:
        rules_lines = []
        for d in extracted.directives:
            marker = "DO" if d.polarity == "do" else "DON'T"
            scope = f" ({d.genre_scope})" if d.genre_scope else ""
            rules_lines.append(f"• [{marker}{scope}] {d.text}")
        rules = "\n".join(rules_lines)
        await message.answer(f"{M.COMMENT_SAVED}\n\nВыделил правила:\n{rules}")
    else:
        await message.answer("✅ Комментарий сохранил, но конкретных правил не выделил.")


# ----------------------------- /directives -----------------------------

async def _send_directives(send) -> None:
    async with get_session() as s:
        directives = await list_all_directives(s, limit=50)
    if not directives:
        # Только кнопка «➕ Добавить» через directives_list_kb с пустым списком
        await send(M.DIRECTIVES_EMPTY, reply_markup=directives_list_kb([]))
        return

    # Группируем: сначала глобальные, потом по жанрам
    globals_: list[UserDirective] = []
    by_genre: dict[str, list[UserDirective]] = {}
    for d in directives:
        if d.genre_scope:
            by_genre.setdefault(d.genre_scope, []).append(d)
        else:
            globals_.append(d)

    lines = [M.DIRECTIVES_HEADER, ""]
    if globals_:
        lines.append("🌐 Глобальные:")
        for d in globals_:
            marker = "✅" if d.polarity == "do" else "🚫"
            lines.append(f"  {marker} {d.text}")
    for genre, items in by_genre.items():
        lines.append(f"\n🎯 Для жанра «{genre}»:")
        for d in items:
            marker = "✅" if d.polarity == "do" else "🚫"
            lines.append(f"  {marker} {d.text}")

    # Кнопки: ➕ Добавить + 🗑 у каждой директивы
    items_for_kb = [(d.id, d.polarity, d.text, d.genre_scope) for d in directives]
    await send("\n".join(lines), reply_markup=directives_list_kb(items_for_kb))


@router.message(Command("directives"))
async def cmd_directives(message: Message) -> None:
    await _send_directives(message.answer)


@router.callback_query(F.data == "menu:directives")
async def on_menu_directives(cb: CallbackQuery) -> None:
    await cb.answer()
    if cb.message:
        await _send_directives(cb.message.answer)


# ----------------------------- добавление примера -----------------------------

@router.callback_query(F.data == "menu:add_example")
async def on_menu_add_example(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ExampleStates.waiting_text)
    await cb.answer()
    if cb.message:
        await cb.message.answer(M.EXAMPLE_PROMPT_TEXT, reply_markup=back_to_menu_kb())


@router.message(ExampleStates.waiting_text, F.text)
async def on_example_text(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/"):
        return
    text = (message.text or "").strip()
    if len(text) < 150:
        await message.answer(M.EXAMPLE_TOO_SHORT, reply_markup=back_to_menu_kb())
        return
    await state.update_data(example_text=text)
    await state.set_state(ExampleStates.waiting_genre)
    await message.answer(M.EXAMPLE_PROMPT_GENRE, reply_markup=genre_choice_kb())


@router.callback_query(F.data.startswith("exgenre:"))
async def on_example_genre(cb: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current != ExampleStates.waiting_genre.state:
        await cb.answer()
        return
    parts = (cb.data or "").split(":")
    if len(parts) != 2:
        await cb.answer()
        return
    genre = parts[1]
    await state.update_data(example_genre=genre)
    await state.set_state(ExampleStates.waiting_score)
    await cb.answer()
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(M.EXAMPLE_PROMPT_SCORE, reply_markup=score_choice_kb())


@router.callback_query(F.data.startswith("exscore:"))
async def on_example_score(cb: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current != ExampleStates.waiting_score.state:
        await cb.answer()
        return
    parts = (cb.data or "").split(":")
    if len(parts) != 2:
        await cb.answer()
        return
    try:
        score = int(parts[1])
    except ValueError:
        await cb.answer()
        return

    data = await state.get_data()
    text = data.get("example_text") or ""
    genre = data.get("example_genre") or "unknown"
    if not text:
        await cb.answer("Текст потерян, попробуй заново", show_alert=True)
        await state.clear()
        return

    s_cfg = get_settings()
    async with get_session() as session:
        ex = await add_style_example(
            session,
            text=text,
            genre=genre,
            source="manual",
            score=score,
            note=f"Manual upload, user score {score}",
        )
        ex_id = ex.id

    await cb.answer("Сохранено")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(
            M.EXAMPLE_SAVED.format(genre=_GENRE_LABELS.get(genre, genre), score=score)
        )

    # Stylist — извлекаем хорошие фразы, если оценка достаточная
    if score >= s_cfg.auto_save_as_example_threshold and cb.message:
        try:
            stylist_res = await extract_style(text)
            async with get_session() as session:
                for phrase, kind in stylist_res.good_phrases:
                    await add_good_phrase(session, phrase=phrase, kind=kind)
            await cb.message.answer(
                M.EXAMPLE_STYLIST_DONE.format(n=len(stylist_res.good_phrases)),
                reply_markup=back_to_menu_kb(),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Stylist on manual example failed: {e}")
            if cb.message:
                await cb.message.answer(
                    "Сохранил, но стилист сейчас занят — фразы извлеку при следующем разе.",
                    reply_markup=back_to_menu_kb(),
                )
    elif cb.message:
        await cb.message.answer(
            "(Оценка ниже 7 — пример сохранён, но фразы не извлекал.)",
            reply_markup=back_to_menu_kb(),
        )
    await state.clear()


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


# ----------------------------- управление директивами (UI) -----------------------------

_POLARITY_MARKER = {"do": "✅", "dont": "🚫"}


def _format_directive_line(d: UserDirective) -> str:
    marker = _POLARITY_MARKER.get(d.polarity, "•")
    scope = f" [{d.genre_scope}]" if d.genre_scope else ""
    return f"{marker}{scope} {d.text}"


@router.callback_query(F.data == "directive:add")
async def on_directive_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DirectiveStates.entering_text)
    await cb.answer()
    if cb.message:
        await cb.message.answer(M.DIRECTIVE_NEW_PROMPT, reply_markup=back_to_menu_kb())


@router.message(DirectiveStates.entering_text, F.text)
async def on_directive_text(message: Message, state: FSMContext) -> None:
    if message.text and message.text.startswith("/"):
        return
    text = (message.text or "").strip()
    if len(text) < 5:
        await message.answer(M.DIRECTIVE_TEXT_TOO_SHORT, reply_markup=back_to_menu_kb())
        return
    if len(text) > 200:
        await message.answer(M.DIRECTIVE_TEXT_TOO_LONG, reply_markup=back_to_menu_kb())
        return
    await state.update_data(directive_text=text)
    await state.set_state(DirectiveStates.choosing_polarity)
    await message.answer(M.DIRECTIVE_NEW_POLARITY, reply_markup=directive_polarity_kb())


@router.callback_query(F.data.startswith("dpolarity:"))
async def on_directive_polarity(cb: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current != DirectiveStates.choosing_polarity.state:
        await cb.answer()
        return
    parts = (cb.data or "").split(":")
    if len(parts) != 2 or parts[1] not in ("do", "dont"):
        await cb.answer()
        return
    await state.update_data(directive_polarity=parts[1])
    await state.set_state(DirectiveStates.choosing_genre)
    await cb.answer()
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(M.DIRECTIVE_NEW_GENRE, reply_markup=directive_genre_kb())


@router.callback_query(F.data.startswith("dgenre:"))
async def on_directive_genre(cb: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current != DirectiveStates.choosing_genre.state:
        await cb.answer()
        return
    parts = (cb.data or "").split(":")
    if len(parts) != 2:
        await cb.answer()
        return
    raw = parts[1]
    genre_scope = None if raw == "global" else raw

    data = await state.get_data()
    text = data.get("directive_text") or ""
    polarity = data.get("directive_polarity") or "do"
    if not text:
        await cb.answer("Текст потерян, начни заново", show_alert=True)
        await state.clear()
        return

    async with get_session() as session:
        await add_user_directive(
            session,
            text=text,
            polarity=polarity,
            genre_scope=genre_scope,
            raw_comment=None,
        )

    await state.clear()
    marker = _POLARITY_MARKER.get(polarity, "•")
    scope = f" [{genre_scope}]" if genre_scope else ""
    await cb.answer("Сохранил")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(
            M.DIRECTIVE_SAVED.format(marker=marker, scope=scope, text=text)
        )
        await _send_directives(cb.message.answer)


@router.callback_query(F.data.startswith("directive:del:"))
async def on_directive_delete_ask(cb: CallbackQuery) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 3:
        await cb.answer()
        return
    try:
        d_id = int(parts[2])
    except ValueError:
        await cb.answer()
        return
    async with get_session() as session:
        d = await session.get(UserDirective, d_id)
    if d is None:
        await cb.answer("Уже удалено", show_alert=True)
        return
    marker = _POLARITY_MARKER.get(d.polarity, "•")
    scope = f" [{d.genre_scope}]" if d.genre_scope else ""
    await cb.answer()
    if cb.message:
        await cb.message.answer(
            M.DIRECTIVE_DELETE_CONFIRM.format(marker=marker, scope=scope, text=d.text),
            reply_markup=confirm_delete_directive_kb(d_id),
        )


@router.callback_query(F.data.startswith("directive:confirm_del:"))
async def on_directive_delete_confirm(cb: CallbackQuery) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 3:
        await cb.answer()
        return
    try:
        d_id = int(parts[2])
    except ValueError:
        await cb.answer()
        return
    async with get_session() as session:
        await deactivate_directive(session, d_id)
    await cb.answer("Удалено")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(M.DIRECTIVE_DELETED)
        await _send_directives(cb.message.answer)

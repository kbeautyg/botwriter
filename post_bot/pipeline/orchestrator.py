"""Pipeline: Planner → Writer ↔ Critic loop.

Алгоритм:
1. Planner: brief → {genre, hook, structure, key_points, must_keep_phrases, tone, close_type}.
2. По жанру плана подбираем few-shot эталоны.
3. Writer: brief + план + few-shot → draft #0.
4. Critic: draft → score (-10..+10) + feedback + must_fix.
5. Если score >= MIN_ACCEPTABLE_SCORE → выдаём; иначе Writer переписывает с feedback'ом.
6. Максимум MAX_REWRITE_ITERATIONS перезаписей, выдаём draft с лучшим score.

Все шаги пишутся в БД: план в Brief.plan_json, каждая итерация — в Draft.
Финальный draft помечается is_final, создаётся Post.
"""
from __future__ import annotations

from dataclasses import dataclass

from post_bot.config import get_settings
from post_bot.db.engine import get_session
from post_bot.db.models import Brief, Draft, Post
from post_bot.db.repository import (
    add_style_example,
    attach_critic_review,
    create_draft,
    create_post,
    get_active_directives,
    get_brief,
    get_good_phrases,
    mark_final_draft,
    set_brief_status,
)
from post_bot.llm.critic import CriticResult, review
from post_bot.llm.planner import Plan, plan_post
from post_bot.llm.stylist import extract_style
from post_bot.llm.writer import WriterResult, write_draft
from post_bot.pipeline.style_retrieval import pick_examples
from post_bot.utils.logger import logger


@dataclass
class PipelineResult:
    post: Post
    final_draft: Draft
    final_score: float
    iterations: int
    plan: Plan
    history: list[tuple[WriterResult, CriticResult]]


async def generate_post(brief_id: int) -> PipelineResult:
    s = get_settings()

    async with get_session() as session:
        brief = await get_brief(session, brief_id)
        if brief is None:
            raise ValueError(f"Brief {brief_id} not found")
        brief_text = brief.combined_input
        if not brief_text:
            raise ValueError(f"Brief {brief_id} is empty")

        target_length = brief.target_length_words
        # Для Planner — только глобальные директивы (жанр ещё не известен)
        global_dirs = await get_active_directives(session, genre=None, limit=20)
        global_directives_list: list[tuple[str, str]] = [
            (d.text, d.polarity) for d in global_dirs
        ]
        # 1) Planner: что писать и как
        await set_brief_status(session, brief, "planning")

    # Planner делаем вне сессии — он не пишет в БД сам, только LLM-вызов
    plan = await plan_post(
        brief_text,
        target_length_words=target_length,
        directives=global_directives_list,
    )
    # Если автор задал длину явно — она перебивает то, что предложил Planner.
    if target_length:
        plan.length_words = target_length
    logger.info(f"Plan: genre={plan.genre} close={plan.close_type} length={plan.length_words}")

    async with get_session() as session:
        brief = await get_brief(session, brief_id)
        if brief is None:
            raise ValueError(f"Brief {brief_id} gone during planning")
        # сохраним план в брифе
        brief.plan_json = {
            "genre": plan.genre,
            "headline": plan.headline,
            "hook": plan.hook,
            "structure": plan.structure,
            "opposition": plan.opposition,
            "we_position": plan.we_position,
            "reader_filter": plan.reader_filter,
            "key_points": plan.key_points,
            "must_keep_phrases": plan.must_keep_phrases,
            "tone": plan.tone,
            "close_type": plan.close_type,
            "close_announcement": plan.close_announcement,
            "length_words": plan.length_words,
            "rationale": plan.rationale,
        }
        await set_brief_status(session, brief, "generating")

        examples = await pick_examples(session, genre=plan.genre or brief.genre_hint, limit=5)
        good_phrases = await get_good_phrases(session, limit=30)
        # Для Writer — глобальные + директивы выбранного жанра
        full_dirs = await get_active_directives(session, genre=plan.genre, limit=30)
        directives_list: list[tuple[str, str]] = [(d.text, d.polarity) for d in full_dirs]

        history: list[tuple[WriterResult, CriticResult]] = []
        best_draft_db: Draft | None = None
        best_score: float = -100.0
        best_writer: WriterResult | None = None

        prev_writer: WriterResult | None = None
        prev_critic: CriticResult | None = None

        for iteration in range(s.max_rewrite_iterations + 1):
            logger.info(f"Pipeline brief={brief_id} iter={iteration}")
            writer_res = await write_draft(
                brief_text=brief_text,
                plan=plan,
                examples=examples,
                good_phrases=good_phrases,
                directives=directives_list,
                genre_hint=plan.genre or brief.genre_hint,
                critic_feedback=prev_critic.feedback if prev_critic else None,
                critic_must_fix=prev_critic.must_fix if prev_critic else None,
                previous_draft=prev_writer.draft if prev_writer else None,
            )

            draft_db = await create_draft(
                session,
                brief_id=brief.id,
                iteration=iteration,
                text=writer_res.draft,
                writer_model=writer_res.model,
                tokens_in=writer_res.tokens_in,
                tokens_out=writer_res.tokens_out,
            )

            critic_res = await review(
                writer_res.draft,
                target_length_words=plan.length_words,
                genre=plan.genre,
            )
            await attach_critic_review(
                session,
                draft_db,
                critic_model=critic_res.model,
                score=critic_res.score,
                breakdown=critic_res.breakdown,
                feedback=critic_res.feedback,
                ai_markers_found=critic_res.ai_markers_found,
                must_fix=critic_res.must_fix,
            )

            history.append((writer_res, critic_res))
            logger.info(
                f"  iter={iteration} score={critic_res.score} "
                f"markers={critic_res.ai_markers_found} "
                f"banned={critic_res.banned_words_found}"
            )

            if critic_res.score > best_score:
                best_score = critic_res.score
                best_draft_db = draft_db
                best_writer = writer_res

            if critic_res.score >= s.min_acceptable_score:
                break

            prev_writer = writer_res
            prev_critic = critic_res

        assert best_draft_db is not None and best_writer is not None

        # Защита: если все итерации дали пустой текст (reasoning-модель сжёг бюджет
        # или OpenAI вернул empty content) — не делаем Post, чтобы не упасть в Telegram.
        if not (best_draft_db.text or "").strip():
            await set_brief_status(session, brief, "cancelled")
            raise RuntimeError(
                "Все итерации дали пустой черновик. Это бывает с reasoning-моделями "
                "(gpt-5.x) при нехватке токенового бюджета. Проверь модель в Variables "
                "или увеличь MAX_REWRITE_ITERATIONS."
            )

        await mark_final_draft(session, best_draft_db)

        post = await create_post(
            session,
            brief_id=brief.id,
            draft=best_draft_db,
            genre=best_writer.genre,
        )
        await set_brief_status(session, brief, "done")

        return PipelineResult(
            post=post,
            final_draft=best_draft_db,
            final_score=best_score,
            iterations=len(history),
            plan=plan,
            history=history,
        )


async def save_post_as_example(post_id: int, *, score: int) -> None:
    """Перенести пост в style_examples + извлечь хорошие фразы.
    Вызывается при rating ≥ threshold или вручную «Сохранить как образец»."""
    from post_bot.db.repository import add_good_phrase  # локально, чтобы не плодить цикл

    text_for_extract: str | None = None
    async with get_session() as session:
        post = await session.get(Post, post_id)
        if not post:
            return
        if post.saved_as_example:
            return
        text = post.edited_text or post.text
        text_for_extract = text
        await add_style_example(
            session,
            text=text,
            genre=post.genre or "unknown",
            source="rated",
            score=score,
            source_post_id=post.id,
            note=f"User rating {score}",
        )
        post.saved_as_example = True

    # Извлекаем стилистические приёмы — отдельной транзакцией, не блокируя save.
    if text_for_extract:
        try:
            stylist_res = await extract_style(text_for_extract)
            async with get_session() as session:
                for phrase, kind in stylist_res.good_phrases:
                    await add_good_phrase(
                        session, phrase=phrase, kind=kind, source_post_id=post_id
                    )
            logger.info(f"Stylist saved {len(stylist_res.good_phrases)} phrases from post {post_id}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Stylist failed for post {post_id}: {e}")

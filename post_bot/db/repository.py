"""Тонкие helpers поверх sessions. CRUD по моделям."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from post_bot.db.models import (
    BadPhrase,
    Brief,
    Draft,
    GoodPhrase,
    Post,
    StyleExample,
    UserDirective,
)


# --- Briefs ---

async def create_brief(session: AsyncSession, tg_user_id: int) -> Brief:
    brief = Brief(tg_user_id=tg_user_id, raw_text="", voice_transcripts=[])
    session.add(brief)
    await session.flush()
    return brief


async def get_brief(session: AsyncSession, brief_id: int) -> Brief | None:
    return await session.get(Brief, brief_id)


async def append_text(session: AsyncSession, brief: Brief, text: str) -> None:
    brief.raw_text = (brief.raw_text + "\n" + text).strip() if brief.raw_text else text.strip()
    await session.flush()


async def append_voice(session: AsyncSession, brief: Brief, transcript: str) -> None:
    current = list(brief.voice_transcripts or [])
    current.append(transcript)
    brief.voice_transcripts = current
    await session.flush()


async def set_brief_status(session: AsyncSession, brief: Brief, status: str) -> None:
    brief.status = status
    if status in ("done", "cancelled"):
        brief.finished_at = datetime.now(timezone.utc)
    await session.flush()


# --- Drafts ---

async def create_draft(
    session: AsyncSession,
    *,
    brief_id: int,
    iteration: int,
    text: str,
    writer_model: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> Draft:
    draft = Draft(
        brief_id=brief_id,
        iteration=iteration,
        text=text,
        writer_model=writer_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    session.add(draft)
    await session.flush()
    return draft


async def attach_critic_review(
    session: AsyncSession,
    draft: Draft,
    *,
    critic_model: str,
    score: float,
    breakdown: dict,
    feedback: str,
    ai_markers_found: list[str],
    must_fix: list[str],
) -> None:
    draft.critic_model = critic_model
    draft.critic_score = score
    draft.critic_breakdown = breakdown
    draft.critic_feedback = feedback
    draft.ai_markers_found = ai_markers_found
    draft.must_fix = must_fix
    await session.flush()


async def mark_final_draft(session: AsyncSession, draft: Draft) -> None:
    draft.is_final = True
    await session.flush()


# --- Posts ---

async def create_post(
    session: AsyncSession,
    *,
    brief_id: int,
    draft: Draft,
    genre: str | None,
) -> Post:
    post = Post(
        brief_id=brief_id,
        final_draft_id=draft.id,
        text=draft.text,
        genre=genre,
    )
    session.add(post)
    await session.flush()
    return post


async def rate_post(
    session: AsyncSession,
    post: Post,
    *,
    rating: int,
    note: str | None = None,
    edited_text: str | None = None,
) -> None:
    post.user_rating = rating
    post.user_note = note
    if edited_text:
        post.edited_text = edited_text
    post.rated_at = datetime.now(timezone.utc)
    await session.flush()


# --- Style examples ---

async def add_style_example(
    session: AsyncSession,
    *,
    text: str,
    genre: str,
    source: str,
    score: int = 10,
    note: str | None = None,
    source_post_id: int | None = None,
) -> StyleExample:
    ex = StyleExample(
        text=text.strip(),
        genre=genre,
        source=source,
        score=score,
        note=note,
        source_post_id=source_post_id,
    )
    session.add(ex)
    await session.flush()
    return ex


async def get_style_examples(
    session: AsyncSession, *, genre: str | None = None, limit: int = 3
) -> list[StyleExample]:
    stmt = select(StyleExample).where(StyleExample.is_active.is_(True))
    if genre:
        stmt = stmt.where(StyleExample.genre == genre)
    stmt = stmt.order_by(StyleExample.score.desc(), StyleExample.created_at.desc()).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def count_style_examples(session: AsyncSession) -> int:
    res = await session.execute(select(StyleExample.id))
    return len(list(res.scalars().all()))


# --- Phrases ---

async def add_good_phrase(
    session: AsyncSession,
    *,
    phrase: str,
    kind: str = "phrase",
    source_post_id: int | None = None,
) -> GoodPhrase:
    gp = GoodPhrase(phrase=phrase.strip(), kind=kind, source_post_id=source_post_id)
    session.add(gp)
    await session.flush()
    return gp


async def add_bad_phrase(
    session: AsyncSession, *, phrase: str, kind: str = "cliche", source: str = "seed"
) -> BadPhrase:
    bp = BadPhrase(phrase=phrase.strip(), kind=kind, source=source)
    session.add(bp)
    await session.flush()
    return bp


async def get_good_phrases(session: AsyncSession, limit: int = 30) -> list[GoodPhrase]:
    stmt = select(GoodPhrase).order_by(GoodPhrase.weight.desc()).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def get_bad_phrases(session: AsyncSession, limit: int = 50) -> list[BadPhrase]:
    stmt = select(BadPhrase).order_by(BadPhrase.weight.desc()).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


# --- User directives ---

async def add_user_directive(
    session: AsyncSession,
    *,
    text: str,
    polarity: str = "do",
    source_post_id: int | None = None,
    raw_comment: str | None = None,
) -> UserDirective:
    d = UserDirective(
        text=text.strip(),
        polarity=polarity if polarity in ("do", "dont") else "do",
        source_post_id=source_post_id,
        raw_comment=raw_comment,
    )
    session.add(d)
    await session.flush()
    return d


async def get_active_directives(
    session: AsyncSession, limit: int = 20
) -> list[UserDirective]:
    stmt = (
        select(UserDirective)
        .where(UserDirective.is_active.is_(True))
        .order_by(UserDirective.weight.desc(), UserDirective.created_at.desc())
        .limit(limit)
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def deactivate_directive(session: AsyncSession, directive_id: int) -> None:
    d = await session.get(UserDirective, directive_id)
    if d:
        d.is_active = False
        await session.flush()

"""Подбор few-shot примеров под жанр. v1 — простая БД-фильтрация по жанру + score."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from post_bot.db.models import StyleExample


async def pick_examples(
    session: AsyncSession,
    *,
    genre: str | None,
    limit: int = 5,
) -> list[StyleExample]:
    """Вернуть до `limit` эталонов: сначала по жанру, потом добивая разнообразием."""
    base = select(StyleExample).where(StyleExample.is_active.is_(True))

    chosen: list[StyleExample] = []
    seen_ids: set[int] = set()

    if genre:
        stmt = base.where(StyleExample.genre == genre).order_by(
            StyleExample.score.desc(), StyleExample.created_at.desc()
        ).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for r in rows:
            if r.id not in seen_ids:
                chosen.append(r)
                seen_ids.add(r.id)

    # Если жанра не хватило — добиваем top-N по score из других жанров.
    if len(chosen) < limit:
        stmt = base.order_by(StyleExample.score.desc(), StyleExample.created_at.desc()).limit(
            limit * 3
        )
        rows = (await session.execute(stmt)).scalars().all()
        for r in rows:
            if len(chosen) >= limit:
                break
            if r.id in seen_ids:
                continue
            chosen.append(r)
            seen_ids.add(r.id)

    return chosen[:limit]

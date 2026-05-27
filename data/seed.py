"""Сидирование БД эталонными данными. Вызывается из __main__ при первом запуске
(идемпотентно: проверяет что уже засеяно).
"""
from __future__ import annotations

from sqlalchemy import select

from data.anti_patterns import BANNED_WORDS
from data.seed_posts import SEED_GOOD_PHRASES, SEED_POSTS
from post_bot.db.engine import get_session
from post_bot.db.models import BadPhrase, GoodPhrase, StyleExample
from post_bot.db.repository import (
    add_bad_phrase,
    add_good_phrase,
    add_style_example,
)
from post_bot.utils.logger import logger


async def seed_if_empty() -> None:
    """Засеять seed-данные, если соответствующих таблиц нет."""
    async with get_session() as s:
        # StyleExample
        cnt = (await s.execute(select(StyleExample.id))).scalars().all()
        if not cnt:
            for p in SEED_POSTS:
                await add_style_example(
                    s, text=p.text, genre=p.genre, source="seed", score=10, note=p.note
                )
            logger.info(f"Засеяно {len(SEED_POSTS)} эталонных постов")

        # GoodPhrase
        gp = (await s.execute(select(GoodPhrase.id))).scalars().all()
        if not gp:
            for phrase, kind in SEED_GOOD_PHRASES:
                await add_good_phrase(s, phrase=phrase, kind=kind)
            logger.info(f"Засеяно {len(SEED_GOOD_PHRASES)} good_phrases")

        # BadPhrase
        bp = (await s.execute(select(BadPhrase.id))).scalars().all()
        if not bp:
            for word in BANNED_WORDS:
                await add_bad_phrase(s, phrase=word, kind="banned_word", source="seed")
            logger.info(f"Засеяно {len(BANNED_WORDS)} banned_words")

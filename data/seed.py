"""Сидирование БД эталонными данными.
- Если БД пустая (первый запуск) — кладём всё.
- Если уже есть Артёмовские эталоны, но нет SAYJI — деактивируем старые
  и добавляем SAYJI. Это переключение на основной референс.
- Если SAYJI уже есть — ничего не трогаем (идемпотентно).
"""
from __future__ import annotations

from sqlalchemy import select, update

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


# Артёмовские обороты, которые НЕ должен использовать SAYJI-голос.
# При миграции на SAYJI деактивируем их в GoodPhrase (is_active нет в схеме —
# просто удалим записи, они продублируются из seed если понадобятся).
_ARTEM_PHRASES_TO_PURGE = [
    "залетают в это как в шабашку",
    "срубить лёгких денег",
    "говноэксперт из каждого утюга",
    "инфоцыгане обещают золотые горы",
    "вкалывать 24/7",
    "отношение как к темке",
    "на расслабоне систему не построить",
    "встать у станка",
    "забудьте про старт с нуля рублей",
    "сфабрикованные результаты",
    "ведясь на чужие обещания",
    "ничего толком, кроме потраченного времени",
    "автономный бизнес, который приносит дивиденды",
    "Открытие с провокации без приветствия (для contrarian-постов)",
    "Прямой адрес «вы» с условием отписки («лучше сразу отпишитесь»)",
]


# Маркер по которому отличаем SAYJI seed: все его посты начинаются с «Привет каждому!»
# или с заголовка с ⚙️. Используем первое для проверки.
_SAYJI_MARKER = "Привет каждому"


async def _count_sayji_seed(session) -> int:
    """Сколько SAYJI seed-эталонов сейчас в БД."""
    res = await session.execute(
        select(StyleExample.id).where(
            StyleExample.source == "seed",
            StyleExample.is_active.is_(True),
        )
    )
    return len(list(res.scalars().all()))


async def _seed_texts_in_db(session) -> set[str]:
    """Тексты уже засеянных эталонов — чтобы не дублировать при добавлении новых."""
    res = await session.execute(
        select(StyleExample.text).where(StyleExample.source == "seed")
    )
    return {row[0] for row in res.all()}


async def _deactivate_old_artem_seed(session) -> int:
    """Старые Артёмовские эталоны (source=seed) деактивируем, чтобы они не подкладывались
    в few-shot. Сами записи не удаляем — мало ли понадобятся."""
    res = await session.execute(
        update(StyleExample)
        .where(StyleExample.source == "seed", StyleExample.is_active.is_(True))
        .values(is_active=False)
    )
    return res.rowcount or 0


async def seed_if_empty() -> None:
    async with get_session() as s:
        # 1. StyleExample — SAYJI как основной референс.
        # Логика: всегда добавляем SAYJI-эталоны, которых ещё нет в БД (по тексту).
        # При первом запуске деактивируем старые Артёмовские эталоны.
        existing_texts = await _seed_texts_in_db(s)
        # На первом запуске Артёмовские эталоны деактивируются:
        has_any_seed = bool(existing_texts)
        if has_any_seed:
            # Если у нас в БД есть какие-то seed, но нет SAYJI — это первый редеплой
            # с миграцией. Деактивируем Артёма.
            has_sayji = any(_SAYJI_MARKER in t for t in existing_texts)
            if not has_sayji:
                deactivated = await _deactivate_old_artem_seed(s)
                if deactivated:
                    logger.info(f"Деактивировано {deactivated} старых seed-эталонов (Артём)")

        added = 0
        for p in SEED_POSTS:
            if p.text not in existing_texts:
                await add_style_example(
                    s, text=p.text, genre=p.genre, source="seed", score=10, note=p.note
                )
                added += 1
        if added:
            logger.info(f"Засеяно {added} новых SAYJI-эталонов (всего в SEED_POSTS: {len(SEED_POSTS)})")

        # 2. GoodPhrase:
        # 2a. ЧИСТКА Артёмовских оборотов — их Writer всё равно видит как
        # «характерная лексика», и они утекают в посты даже когда жанр SAYJI.
        from sqlalchemy import delete
        purged = 0
        for ph in _ARTEM_PHRASES_TO_PURGE:
            res = await s.execute(delete(GoodPhrase).where(GoodPhrase.phrase == ph))
            purged += res.rowcount or 0
        if purged:
            logger.info(f"Удалено {purged} Артёмовских good_phrases (миграция на SAYJI)")

        # 2b. Добавляем SAYJI good_phrases если их ещё нет.
        sayji_phrase_check = await s.execute(
            select(GoodPhrase.id).where(GoodPhrase.phrase.like("%Привет каждому%"))
        )
        if sayji_phrase_check.first() is None:
            for phrase, kind in SEED_GOOD_PHRASES:
                await add_good_phrase(s, phrase=phrase, kind=kind)
            logger.info(f"Засеяно {len(SEED_GOOD_PHRASES)} SAYJI good_phrases")

        # 3. BadPhrase — banned_words нейтральны, добавляем если пусто.
        bp = (await s.execute(select(BadPhrase.id))).scalars().all()
        if not bp:
            for word in BANNED_WORDS:
                await add_bad_phrase(s, phrase=word, kind="banned_word", source="seed")
            logger.info(f"Засеяно {len(BANNED_WORDS)} banned_words")

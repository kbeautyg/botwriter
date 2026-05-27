"""Smoke: пайплайн на простых тезисах не падает в очевидные ИИ-маркеры.

Использует временную БД через monkeypatching CONFIG.db_path.
"""
from __future__ import annotations

import os
import re
import tempfile

import pytest

pytestmark = [pytest.mark.llm, pytest.mark.asyncio]


BAD_TOKENS_PATTERNS: list[tuple[str, str]] = [
    (r"\bКто\s+Мы\?", "заголовок «Кто Мы?»"),
    (r"\bЧто\s+Мы\s+Вам\s+дадим", "заголовок «Что Мы Вам дадим»"),
    (r"Подписывайтесь[\s,!.]*$", "пустая концовка «Подписывайтесь!»"),
    (r"Всем\s+добра", "концовка «Всем добра»"),
    (r"До\s+новых\s+встреч", "концовка «До новых встреч»"),
    (r"\bдорогие\s+(подписчики|друзья|читатели)", "обращение «дорогие …»"),
    (r"\bтаким образом\b", "канцелярит «таким образом»"),
    (r"\bв заключение\b", "канцелярит «в заключение»"),
]


@pytest.fixture
async def fresh_db(monkeypatch):
    """Подменить db_path на временный файл и инициализировать."""
    tmpdir = tempfile.mkdtemp(prefix="post-bot-test-")
    db_path = os.path.join(tmpdir, "test.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)

    # сбросить lru_cache на settings
    from post_bot import config
    config.get_settings.cache_clear()

    # сбросить engine
    import post_bot.db.engine as engine_mod
    engine_mod._engine = None
    engine_mod._sessionmaker = None

    from post_bot.db.engine import init_db
    await init_db()

    from data.seed import seed_if_empty
    await seed_if_empty()
    yield db_path


async def test_pipeline_no_obvious_ai_markers(fresh_db):
    from post_bot.db.engine import get_session
    from post_bot.db.repository import append_text, create_brief
    from post_bot.pipeline.orchestrator import generate_post

    # Тезисы похожие на типичный кейс — представление и хук про деньги
    brief_text = (
        "Тема: почему люди сливают бюджет на YouTube за первый месяц. "
        "Тезисы: 1) Думают что нужен сразу дорогой монтаж — это миф, нужен сценарий. "
        "2) Заливают вертикалки и горизонталки одной стратегией — не работает. "
        "3) Не сидят на алгоритмах, а копируют тренды трёхмесячной давности. "
        "Концовка: следующий пост про реальные суммы старта."
    )

    async with get_session() as s:
        brief = await create_brief(s, tg_user_id=123)
        await append_text(s, brief, brief_text)
        brief_id = brief.id

    result = await generate_post(brief_id)
    text = result.final_draft.text

    print(f"\n--- GENERATED (score={result.final_score}, iter={result.iterations}) ---")
    print(text)
    print("--- /GENERATED ---")

    found_issues: list[str] = []
    for pattern, why in BAD_TOKENS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            found_issues.append(why)

    assert not found_issues, (
        f"Pipeline produced text with AI markers: {found_issues}\n\nText:\n{text}"
    )
    # И средний бал должен быть хотя бы рабочим
    assert result.final_score >= 3, f"Pipeline final score too low: {result.final_score}"

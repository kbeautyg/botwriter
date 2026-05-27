"""Регрессия: Critic должен жёстко отбраковывать плохой пост («Кто Мы? 👨‍💻»).

Если падает — значит rubric Critic'а слишком мягкий или промпт сломан.
score ≤ -3 = «явно ИИшный текст, есть штампы».
"""
from __future__ import annotations

import pytest

from data.seed_posts import SEED_BAD_POSTS
from post_bot.llm.critic import review

pytestmark = [pytest.mark.llm, pytest.mark.asyncio]


@pytest.mark.parametrize("bad", SEED_BAD_POSTS, ids=lambda b: b.genre)
async def test_critic_rejects_bad_posts(bad):
    res = await review(bad.text)
    assert res.score <= -3, (
        f"Critic gave bad post '{bad.genre}' score {res.score} (expected ≤ -3).\n"
        f"breakdown={res.breakdown}\n"
        f"ai_markers={res.ai_markers_found}\n"
        f"banned={res.banned_words_found}\n"
        f"feedback={res.feedback}\n"
        "Это анти-эталон. Critic обязан его узнавать."
    )
    # Должны найтись маркеры — иначе он просто угадал низкий скор
    assert res.ai_markers_found, (
        f"Critic gave bad post a low score but didn't list any ai_markers_found. "
        f"Это значит rubric не работает по существу — проверь промпт."
    )

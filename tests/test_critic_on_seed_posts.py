"""Регрессия: Critic должен оценивать эталонные посты Артёма ≥ 7.

Если падает — значит промпт Critic'а уехал от их голоса. Откатываемся к предыдущей версии.
Помечено `llm` → пропускается без OPENAI_API_KEY.
"""
from __future__ import annotations

import pytest

from data.seed_posts import SEED_POSTS
from post_bot.llm.critic import review

pytestmark = [pytest.mark.llm, pytest.mark.asyncio]


@pytest.mark.parametrize("seed", SEED_POSTS, ids=lambda s: s.genre)
async def test_critic_likes_seed_posts(seed):
    res = await review(seed.text)
    assert res.score >= 7, (
        f"Critic gave seed post '{seed.genre}' a score of {res.score} (< 7).\n"
        f"breakdown={res.breakdown}\n"
        f"ai_markers={res.ai_markers_found}\n"
        f"banned={res.banned_words_found}\n"
        f"feedback={res.feedback}\n"
        f"must_fix={res.must_fix}\n"
        "Это эталон. Если критик его не узнаёт — промпт сломан."
    )

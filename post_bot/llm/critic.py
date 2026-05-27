"""Critic agent: оценивает draft по rubric'у, ищет ИИ-маркеры."""
from __future__ import annotations

from dataclasses import dataclass, field

from post_bot.config import get_settings
from post_bot.llm.client import chat
from post_bot.llm.prompts import CRITIC_SYSTEM
from post_bot.utils.logger import logger


@dataclass
class CriticResult:
    score: float  # -10..+10
    breakdown: dict = field(default_factory=dict)
    ai_markers_found: list[str] = field(default_factory=list)
    banned_words_found: list[str] = field(default_factory=list)
    feedback: str = ""
    must_fix: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except (ValueError, TypeError):
        return lo
    return max(lo, min(hi, v))


async def review(draft_text: str, *, target_length_words: int | None = None) -> CriticResult:
    s = get_settings()
    word_count = len(draft_text.split())
    length_block = ""
    if target_length_words:
        length_block = (
            f"\n═══ ЦЕЛЕВАЯ ДЛИНА ═══\n"
            f"Автор просил ~{target_length_words} слов. В драфте сейчас примерно {word_count} слов.\n"
            f"Если отклонение > ±20% — это нарушение, обязательно в must_fix.\n"
        )
    user_prompt = (
        "Оцени этот пост по rubric'у. Найди все ИИ-маркеры и запрещённые слова.\n"
        f"{length_block}\n"
        "═══ ТЕКСТ ПОСТА ═══\n"
        f"{draft_text.strip()}\n"
        "═══ /ТЕКСТ ═══\n\n"
        "Верни строгий JSON по формату из системной инструкции."
    )
    logger.info(f"Critic: model={s.model_critic}, draft_chars={len(draft_text)}")
    res = await chat(
        model=s.model_critic,
        system=CRITIC_SYSTEM,
        user=user_prompt,
        temperature=0.2,
        max_tokens=1500,
        json_mode=True,
    )
    payload = res.parse_json()

    score = _clamp(payload.get("score", 0), -10, 10)
    breakdown_raw = payload.get("breakdown") or {}
    breakdown = {
        "liveliness": _clamp(breakdown_raw.get("liveliness"), 0, 10),
        "authenticity": _clamp(breakdown_raw.get("authenticity"), 0, 10),
        "originality": _clamp(breakdown_raw.get("originality"), 0, 10),
        "anti_ai": _clamp(breakdown_raw.get("anti_ai"), 0, 10),
    }
    ai_markers = list(payload.get("ai_markers_found") or [])
    banned = list(payload.get("banned_words_found") or [])
    feedback = (payload.get("feedback") or "").strip()
    must_fix = [x for x in (payload.get("must_fix") or []) if isinstance(x, str) and x.strip()]

    return CriticResult(
        score=round(score, 1),
        breakdown=breakdown,
        ai_markers_found=ai_markers,
        banned_words_found=banned,
        feedback=feedback,
        must_fix=must_fix,
        tokens_in=res.tokens_in,
        tokens_out=res.tokens_out,
        model=s.model_critic,
    )

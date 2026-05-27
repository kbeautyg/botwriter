"""Critic agent: оценивает draft по rubric'у, ищет ИИ-маркеры и voice-маркеры."""
from __future__ import annotations

from dataclasses import dataclass, field

from data.genre_rules import format_for_critic
from post_bot.config import get_settings
from post_bot.llm.client import chat
from post_bot.llm.prompts import CRITIC_SYSTEM
from post_bot.utils.logger import logger


@dataclass
class CriticResult:
    score: float  # -10..+10
    breakdown: dict = field(default_factory=dict)
    ai_markers_found: list[str] = field(default_factory=list)
    voice_markers_found: list[str] = field(default_factory=list)
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


async def review(
    draft_text: str,
    *,
    target_length_words: int | None = None,
    genre: str | None = None,
) -> CriticResult:
    s = get_settings()
    word_count = len(draft_text.split())

    parts: list[str] = []
    if target_length_words:
        parts.append(
            f"═══ ЦЕЛЕВАЯ ДЛИНА ═══\n"
            f"Автор просил ~{target_length_words} слов. В драфте сейчас примерно {word_count} слов.\n"
            f"Если отклонение > ±20% — нарушение, обязательно в must_fix."
        )
    if genre:
        genre_block = format_for_critic(genre)
        if genre_block:
            parts.append(genre_block)

    extra = ("\n\n".join(parts) + "\n\n") if parts else ""

    user_prompt = (
        "Оцени этот пост по rubric'у. Найди все ИИ-маркеры и запрещённые слова. "
        "Проверь voice_markers — есть ли характерные обороты автора.\n\n"
        f"{extra}"
        "═══ ТЕКСТ ПОСТА ═══\n"
        f"{draft_text.strip()}\n"
        "═══ /ТЕКСТ ═══\n\n"
        "Верни строгий JSON по формату из системной инструкции."
    )
    logger.info(f"Critic: model={s.model_critic}, draft_chars={len(draft_text)}, genre={genre}")
    res = await chat(
        model=s.model_critic,
        system=CRITIC_SYSTEM,
        user=user_prompt,
        temperature=0.2,
        max_tokens=1500,
        json_mode=True,
    )
    payload = res.parse_json()

    breakdown_raw = payload.get("breakdown") or {}
    breakdown = {
        "liveliness": _clamp(breakdown_raw.get("liveliness"), 0, 10),
        "authenticity": _clamp(breakdown_raw.get("authenticity"), 0, 10),
        "originality": _clamp(breakdown_raw.get("originality"), 0, 10),
        "anti_ai": _clamp(breakdown_raw.get("anti_ai"), 0, 10),
        "voice_markers": _clamp(breakdown_raw.get("voice_markers"), 0, 3),
    }

    # Если модель не вернула score — пересчитаем сами по формуле.
    raw_score = payload.get("score")
    if raw_score is None:
        voice_norm = breakdown["voice_markers"] * 10 / 3
        avg = (
            breakdown["liveliness"]
            + breakdown["authenticity"]
            + breakdown["originality"]
            + breakdown["anti_ai"]
            + voice_norm
        ) / 5
        score = avg * 2 - 10
    else:
        score = _clamp(raw_score, -10, 10)

    ai_markers = list(payload.get("ai_markers_found") or [])
    voice_markers = list(payload.get("voice_markers_found") or [])
    banned = list(payload.get("banned_words_found") or [])
    feedback = (payload.get("feedback") or "").strip()
    must_fix = [x for x in (payload.get("must_fix") or []) if isinstance(x, str) and x.strip()]

    return CriticResult(
        score=round(score, 1),
        breakdown=breakdown,
        ai_markers_found=ai_markers,
        voice_markers_found=voice_markers,
        banned_words_found=banned,
        feedback=feedback,
        must_fix=must_fix,
        tokens_in=res.tokens_in,
        tokens_out=res.tokens_out,
        model=s.model_critic,
    )

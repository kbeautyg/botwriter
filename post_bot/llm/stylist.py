"""Stylist: извлекает «хорошие фразы» и структурные приёмы из одобренного поста.

Вызывается при сохранении поста как образца (rating ≥ threshold).
Извлечённое попадает в GoodPhrase и используется в Writer-промпте.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from post_bot.config import get_settings
from post_bot.llm.client import chat
from post_bot.llm.prompts import STYLIST_SYSTEM
from post_bot.utils.logger import logger


@dataclass
class StylistResult:
    good_phrases: list[tuple[str, str]] = field(default_factory=list)  # (phrase, kind)
    tokens_in: int = 0
    tokens_out: int = 0


async def extract_style(post_text: str) -> StylistResult:
    s = get_settings()
    user_prompt = (
        "Вот пост, который автор оценил высоко. Извлеки авторский голос — "
        "конкретные обороты и структурные приёмы.\n\n"
        "═══ ТЕКСТ ═══\n"
        f"{post_text.strip()}\n"
        "═══ /ТЕКСТ ═══\n\n"
        "Верни JSON по формату из системной инструкции."
    )
    res = await chat(
        model=s.model_stylist,
        system=STYLIST_SYSTEM,
        user=user_prompt,
        temperature=0.3,
        max_tokens=2500,  # reasoning-моделям мало стандартных
        json_mode=True,
    )
    payload = res.parse_json()
    phrases: list[tuple[str, str]] = []
    for p in payload.get("good_phrases") or []:
        if isinstance(p, str) and p.strip():
            phrases.append((p.strip(), "phrase"))
    for st in payload.get("good_structures") or []:
        if isinstance(st, str) and st.strip():
            phrases.append((st.strip(), "structure"))
    logger.info(f"Stylist extracted {len(phrases)} phrases/structures")
    return StylistResult(good_phrases=phrases, tokens_in=res.tokens_in, tokens_out=res.tokens_out)

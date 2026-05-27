"""Извлекает из свободного комментария автора 1-3 структурированных директивы."""
from __future__ import annotations

from dataclasses import dataclass, field

from post_bot.config import get_settings
from post_bot.llm.client import chat
from post_bot.llm.prompts import DIRECTIVE_EXTRACTOR_SYSTEM
from post_bot.utils.logger import logger


@dataclass
class ExtractedDirective:
    text: str
    polarity: str  # do | dont


@dataclass
class FeedbackExtractResult:
    directives: list[ExtractedDirective] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


async def extract_directives(comment_text: str) -> FeedbackExtractResult:
    s = get_settings()
    user_prompt = (
        "═══ КОММЕНТАРИЙ АВТОРА ═══\n"
        f"{comment_text.strip()}\n"
        "═══ /КОММЕНТАРИЙ ═══\n\n"
        "Извлеки 0-3 директивы. Строгий JSON по формату."
    )
    res = await chat(
        model=s.model_stylist,
        system=DIRECTIVE_EXTRACTOR_SYSTEM,
        user=user_prompt,
        temperature=0.2,
        max_tokens=600,
        json_mode=True,
    )
    payload = res.parse_json()
    items: list[ExtractedDirective] = []
    for d in payload.get("directives") or []:
        if not isinstance(d, dict):
            continue
        text = (d.get("text") or "").strip()
        polarity = (d.get("polarity") or "do").strip().lower()
        if polarity not in ("do", "dont"):
            polarity = "do"
        if text:
            items.append(ExtractedDirective(text=text, polarity=polarity))
    logger.info(f"FeedbackExtractor: {len(items)} directives from {len(comment_text)} chars")
    return FeedbackExtractResult(
        directives=items, tokens_in=res.tokens_in, tokens_out=res.tokens_out
    )

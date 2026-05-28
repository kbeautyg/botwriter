"""Общая обёртка над OpenAI. Async-клиент, кэш, retry на параметрах.

Адаптация под reasoning-модели (gpt-5.x/o1/o3/o4/gpt-4.1):
они не принимают `temperature` и хотят `max_completion_tokens` вместо `max_tokens`.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache

from openai import AsyncOpenAI

from post_bot.config import get_settings
from post_bot.utils.logger import logger


_REASONING_RE = re.compile(r"^(gpt-5|o1|o3|o4|gpt-4\.1)", re.IGNORECASE)


def _is_reasoning(model: str) -> bool:
    return bool(_REASONING_RE.match(model or ""))


@lru_cache(maxsize=1)
def get_async_openai() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url or None)


@dataclass
class ChatResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    raw_finish: str

    def parse_json(self) -> dict:
        """Извлечь JSON из ответа модели даже если он обёрнут в ```json…``` или текст."""
        t = self.text.strip()
        # ```json … ```
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", t)
        if m:
            t = m.group(1)
        else:
            # первый { … последний }
            first = t.find("{")
            last = t.rfind("}")
            if first != -1 and last != -1 and last > first:
                t = t[first : last + 1]
        try:
            return json.loads(t)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}; raw text: {self.text[:300]!r}")
            return {}


MAX_TOKEN_CEILING = 16000


async def chat(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.8,
    max_tokens: int = 2000,
    json_mode: bool = False,
) -> ChatResult:
    """Один-shot chat completion с авто-адаптацией под reasoning-модели.

    Для reasoning (gpt-5.x/o1/o3/o4/gpt-4.1) — авто-retry с удвоением бюджета,
    если content пустой (reasoning сожрал все токены).
    """
    client = get_async_openai()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    is_reasoning = _is_reasoning(model)
    # Для reasoning-моделей сразу даём минимум 6000 токенов — иначе reasoning
    # сожрёт весь бюджет и content вернётся пустым.
    if is_reasoning and max_tokens < 6000:
        max_tokens = max(max_tokens, 6000)

    if is_reasoning:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
        }
    else:
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_err: Exception | None = None
    empty_retries = 0  # сколько раз удваивали бюджет из-за пустого ответа

    for attempt in range(5):
        try:
            resp = await client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            finish = getattr(resp.choices[0], "finish_reason", "") or ""
            usage = getattr(resp, "usage", None)

            # Пустой content + finish=length → reasoning сжёг бюджет.
            # Удваиваем max_completion_tokens до потолка.
            if not text and finish in ("length", "stop") and empty_retries < 2:
                current = (
                    kwargs.get("max_completion_tokens")
                    or kwargs.get("max_tokens")
                    or max_tokens
                )
                new_max = min(current * 2, MAX_TOKEN_CEILING)
                if new_max > current:
                    empty_retries += 1
                    logger.warning(
                        f"Empty content from {model} (finish={finish}). "
                        f"Doubling token budget: {current} → {new_max}"
                    )
                    if "max_completion_tokens" in kwargs:
                        kwargs["max_completion_tokens"] = new_max
                    if "max_tokens" in kwargs:
                        kwargs["max_tokens"] = new_max
                    continue

            return ChatResult(
                text=text,
                model=model,
                tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                raw_finish=finish,
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e).lower()
            # Адаптация неподдерживаемых параметров
            if "max_tokens" in msg and "max_completion_tokens" in msg:
                if "max_tokens" in kwargs:
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    logger.info(f"Switched to max_completion_tokens for {model}")
                    continue
            if "temperature" in msg and ("unsupported" in msg or "only" in msg or "default" in msg):
                kwargs.pop("temperature", None)
                logger.info(f"Dropped temperature for {model}")
                continue
            if "response_format" in msg and "unsupported" in msg:
                kwargs.pop("response_format", None)
                logger.info(f"Dropped response_format for {model}")
                continue
            logger.warning(f"OpenAI attempt {attempt + 1} failed: {e!r}")
            await asyncio.sleep(0.5 * (attempt + 1))

    raise RuntimeError(f"OpenAI failed after 5 attempts: {last_err!r}")

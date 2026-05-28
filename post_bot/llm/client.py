"""Унифицированный LLM-клиент.

Поддерживаемые провайдеры:
- OpenAI (модели gpt-*, o1/o3/o4, whisper-*) — основной, используется по дефолту.
- Anthropic (модели claude-*) — текстовые задачи (writer/critic/planner/stylist).

Выбор провайдера автоматический по имени модели:
- начинается с «claude» → Anthropic
- остальное → OpenAI

Адаптации:
- Reasoning-модели OpenAI (gpt-5.x/o1/o3/o4/gpt-4.1): max_completion_tokens
  вместо max_tokens, без temperature; авто-retry с удвоением бюджета при empty content.
- Anthropic: system промпт идёт отдельным параметром, не в messages.
- JSON-mode для Claude эмулируется через инструкцию (нативного response_format нет).
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


def _is_claude(model: str) -> bool:
    return bool(model) and model.lower().startswith("claude")


def _is_reasoning(model: str) -> bool:
    return bool(_REASONING_RE.match(model or ""))


@lru_cache(maxsize=1)
def get_async_openai() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url or None)


@lru_cache(maxsize=1)
def get_async_anthropic():
    """Ленивая инициализация Anthropic-клиента."""
    s = get_settings()
    if not s.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY не задан, но выбрана Claude-модель. "
            "Добавь ANTHROPIC_API_KEY в Variables на Railway, или переключи "
            "MODEL_WRITER/CRITIC/PLANNER/STYLIST обратно на gpt-4o."
        )
    from anthropic import AsyncAnthropic  # ленивый импорт — пакет опциональный
    return AsyncAnthropic(api_key=s.anthropic_api_key, base_url=s.anthropic_base_url or None)


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


# ============================================================================
# Anthropic-провайдер
# ============================================================================

async def _chat_anthropic(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> ChatResult:
    client = get_async_anthropic()
    # Anthropic max_tokens до 8192 для Sonnet, для Opus/Haiku разные пределы.
    # Безопасный потолок — 8000, плюс есть extended-output beta для большего.
    capped_max = min(max_tokens, 8000)

    # Эмулируем JSON-mode инструкцией: добавляем требование к системному промпту.
    sys_prompt = system
    if json_mode:
        sys_prompt = (
            system.rstrip()
            + "\n\nВАЖНО: верни СТРОГО валидный JSON, без markdown-обёртки ```json. "
            "Только JSON-объект, начиная с { и заканчивая }."
        )

    kwargs: dict = {
        "model": model,
        "max_tokens": capped_max,
        "temperature": min(max(temperature, 0.0), 1.0),
        "system": sys_prompt,
        "messages": [{"role": "user", "content": user}],
    }

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.messages.create(**kwargs)
            # Anthropic возвращает content как список блоков (TextBlock).
            text_parts = []
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
            text = "".join(text_parts).strip()
            usage = getattr(resp, "usage", None)
            return ChatResult(
                text=text,
                model=model,
                tokens_in=getattr(usage, "input_tokens", 0) or 0,
                tokens_out=getattr(usage, "output_tokens", 0) or 0,
                raw_finish=getattr(resp, "stop_reason", "") or "",
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(f"Anthropic attempt {attempt + 1} failed: {e!r}")
            await asyncio.sleep(0.5 * (attempt + 1))

    raise RuntimeError(f"Anthropic failed after 3 attempts: {last_err!r}")


# ============================================================================
# OpenAI-провайдер
# ============================================================================

async def _chat_openai(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> ChatResult:
    client = get_async_openai()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    is_reasoning = _is_reasoning(model)
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
    empty_retries = 0

    for attempt in range(5):
        try:
            resp = await client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            finish = getattr(resp.choices[0], "finish_reason", "") or ""
            usage = getattr(resp, "usage", None)

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


# ============================================================================
# Единый chat() — диспетчер по провайдеру
# ============================================================================

async def chat(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.8,
    max_tokens: int = 2000,
    json_mode: bool = False,
) -> ChatResult:
    """Универсальная функция. Сама определяет провайдера по имени модели."""
    if _is_claude(model):
        return await _chat_anthropic(
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
    return await _chat_openai(
        model=model,
        system=system,
        user=user,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )

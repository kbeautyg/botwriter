"""Whisper STT: голосовое → текст. Поддержка ogg/opus/mp3/wav/m4a."""
from __future__ import annotations

from io import BytesIO

from post_bot.config import get_settings
from post_bot.llm.client import get_async_openai
from post_bot.utils.logger import logger

MAX_FILE_MB = 25


async def transcribe(audio_bytes: bytes, filename: str = "voice.ogg", language: str = "ru") -> str:
    """Расшифровать голосовое сообщение.

    audio_bytes: сырое содержимое файла (например, .ogg из Telegram).
    filename: подсказка по расширению для Whisper API.
    """
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        # На MVP — просто warn. Для длинных голосовух (>25МБ ≈ 30+ мин) надо сплит,
        # но Артём вряд ли шлёт такие.
        logger.warning(f"Voice {filename} = {size_mb:.1f}MB > {MAX_FILE_MB}MB — may fail")

    s = get_settings()
    client = get_async_openai()
    buf = BytesIO(audio_bytes)
    buf.name = filename
    resp = await client.audio.transcriptions.create(
        model=s.model_stt,
        file=buf,
        language=language,
    )
    text = (getattr(resp, "text", "") or "").strip()
    logger.info(f"Whisper: {size_mb:.2f}MB → {len(text)} chars")
    return text

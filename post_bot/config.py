"""Конфиг через pydantic-settings. Читает .env."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_db_path() -> str:
    """На Railway данные персистятся только на смонтированном volume (/data).
    Локально удобнее держать БД рядом с проектом.
    """
    on_railway = bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
    )
    return "/data/post_bot.sqlite" if on_railway else "./data/post_bot.sqlite"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str = Field(..., description="BotFather token")
    # ВАЖНО: храним как строку, чтобы pydantic-settings не пытался JSON-декодировать.
    # Парсим в свойстве allowed_user_ids. Поддерживаемые форматы:
    #   "123"            -> [123]
    #   "123,456,789"    -> [123, 456, 789]
    #   "[1, 2, 3]"      -> [1, 2, 3]   (JSON, на случай если кто-то так задаст)
    allowed_user_ids_raw: str = Field("", alias="ALLOWED_USER_IDS")

    # OpenAI
    openai_api_key: str = Field(...)
    openai_base_url: str | None = None
    model_writer: str = "gpt-4o"
    model_critic: str = "gpt-4o-mini"
    model_stylist: str = "gpt-4o-mini"
    model_stt: str = "whisper-1"

    # DB — автоматически /data/... на Railway, ./data/... локально.
    # Можно переопределить через env DB_PATH.
    db_path: str = Field(default_factory=_default_db_path)

    # Pipeline
    max_rewrite_iterations: int = 2
    min_acceptable_score: int = 5
    auto_save_as_example_threshold: int = 7

    # Logging
    log_level: str = "INFO"

    @property
    def allowed_user_ids(self) -> list[int]:
        raw = (self.allowed_user_ids_raw or "").strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                return [int(x) for x in json.loads(raw)]
            except (ValueError, json.JSONDecodeError):
                return []
        return [int(x.strip()) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]

    @property
    def db_url(self) -> str:
        path = Path(self.db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

"""Конфиг через pydantic-settings. Читает .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram
    bot_token: str = Field(..., description="BotFather token")
    allowed_user_ids: list[int] = Field(default_factory=list)

    # OpenAI
    openai_api_key: str = Field(...)
    openai_base_url: str | None = None
    model_writer: str = "gpt-4o"
    model_critic: str = "gpt-4o-mini"
    model_stylist: str = "gpt-4o-mini"
    model_stt: str = "whisper-1"

    # DB
    db_path: str = "./data/post_bot.sqlite"

    # Pipeline
    max_rewrite_iterations: int = 2
    min_acceptable_score: int = 5
    auto_save_as_example_threshold: int = 7

    # Logging
    log_level: str = "INFO"

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @property
    def db_url(self) -> str:
        path = Path(self.db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

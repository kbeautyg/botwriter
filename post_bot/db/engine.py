"""Async engine + сессии. Один на процесс."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from post_bot.config import get_settings
from post_bot.db.models import Base
from post_bot.utils.logger import logger

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.db_url, echo=False, future=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


# Лёгкие миграции для SQLite. Применяются после create_all.
# Каждый кортеж — (table, column, sql_type). Применяется через ALTER TABLE ADD COLUMN
# только если колонки ещё нет (идемпотентно).
_PENDING_COLUMNS: list[tuple[str, str, str]] = [
    ("briefs", "target_length_words", "INTEGER"),
    ("briefs", "plan_json", "JSON"),
]


async def _migrate(conn) -> None:
    """Добавить колонки, которые могут отсутствовать в существующих БД."""
    for table, col, sql_type in _PENDING_COLUMNS:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}
        if col not in existing:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}"))
                logger.info(f"Migration: added {table}.{col} {sql_type}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Migration {table}.{col} failed: {e}")


async def init_db() -> None:
    """Создать таблицы + донакатить колонки. Идемпотентно."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    _get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

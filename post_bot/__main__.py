"""Entry-point: инициализация БД, сидинг, запуск бота."""
from __future__ import annotations

import asyncio
import os
import sys


_REQUIRED_ENVS = ("BOT_TOKEN", "OPENAI_API_KEY")


def _preflight_envs() -> None:
    """Проверка обязательных переменных окружения ДО импорта pydantic-settings.

    Иначе pydantic выдаст 30-строчный traceback вместо понятного сообщения.
    """
    missing = [name for name in _REQUIRED_ENVS if not os.getenv(name)]
    if not missing:
        return

    bar = "=" * 70
    print(bar, file=sys.stderr, flush=True)
    print("[FATAL] Missing required environment variables:", file=sys.stderr, flush=True)
    for name in missing:
        print(f"  - {name}", file=sys.stderr, flush=True)
    print("", file=sys.stderr, flush=True)
    print("Fix:", file=sys.stderr, flush=True)
    print("  Railway: Project -> your service -> Variables -> Add Variable", file=sys.stderr, flush=True)
    print("           (then: Deploy -> Redeploy, иначе не подхватит)", file=sys.stderr, flush=True)
    print("  Local:   create .env using .env.example as template", file=sys.stderr, flush=True)
    print(bar, file=sys.stderr, flush=True)
    sys.exit(2)


_preflight_envs()


from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402

from post_bot.bot.handlers import router as main_router  # noqa: E402
from post_bot.bot.middleware import WhitelistMiddleware  # noqa: E402
from post_bot.config import get_settings  # noqa: E402
from post_bot.db.engine import init_db  # noqa: E402
from post_bot.utils.logger import logger, setup_logger  # noqa: E402


async def _run() -> None:
    setup_logger()
    s = get_settings()
    logger.info(
        f"Starting post-draft-bot · writer={s.model_writer} critic={s.model_critic} "
        f"stt={s.model_stt} allowed_ids={s.allowed_user_ids}"
    )

    # Диагностика БД ДО init — видно состояние файла перед миграциями
    from pathlib import Path
    db_path = Path(s.db_path).resolve()
    db_exists = db_path.exists()
    db_size = db_path.stat().st_size if db_exists else 0
    logger.info(
        f"DB path resolved: {db_path} (exists={db_exists}, size={db_size} bytes)"
    )
    if not str(db_path).startswith(("/data", "/app/data")) and "RAILWAY" in os.environ.get(
        "RAILWAY_PROJECT_ID", "") + os.environ.get("RAILWAY_ENVIRONMENT", ""):
        logger.warning(
            "⚠️  DB_PATH вне /data — БД будет ПОТЕРЯНА при следующем deploy. "
            "Поставь Variables → DB_PATH=/data/post_bot.sqlite и смонтируй Volume на /data."
        )

    await init_db()
    logger.info("DB schema initialized (create_all + migrations)")

    # Считаем содержимое БД после миграций — видно, сохранились ли данные
    from sqlalchemy import func, select
    from post_bot.db.engine import get_session
    from post_bot.db.models import Post, StyleExample, UserDirective
    async with get_session() as session:
        n_dir = (await session.execute(select(func.count(UserDirective.id)))).scalar() or 0
        n_post = (await session.execute(select(func.count(Post.id)))).scalar() or 0
        n_ex = (await session.execute(select(func.count(StyleExample.id)))).scalar() or 0
    logger.info(f"DB content: directives={n_dir}, posts={n_post}, style_examples={n_ex}")

    # Сидим эталоны/фразы только если ещё пусто
    from data.seed import seed_if_empty
    await seed_if_empty()

    bot = Bot(token=s.bot_token, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(WhitelistMiddleware())
    dp.callback_query.middleware(WhitelistMiddleware())

    dp.include_router(main_router)

    me = await bot.get_me()
    logger.info(f"Bot @{me.username} ready (id={me.id}). Polling…")

    try:
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()

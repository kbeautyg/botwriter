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

    await init_db()
    logger.info("DB initialized")

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

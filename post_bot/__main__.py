"""Entry-point: инициализация БД, сидинг, запуск бота."""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from post_bot.bot.handlers import router as main_router
from post_bot.bot.middleware import WhitelistMiddleware
from post_bot.config import get_settings
from post_bot.db.engine import init_db
from post_bot.utils.logger import logger, setup_logger


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

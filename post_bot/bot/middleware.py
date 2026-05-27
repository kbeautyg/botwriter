"""Middleware: whitelist по user_id."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from post_bot.bot.messages import NO_ACCESS
from post_bot.config import get_settings
from post_bot.utils.logger import logger


class WhitelistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        allowed = get_settings().allowed_user_ids
        if user_id is None or (allowed and user_id not in allowed):
            logger.warning(f"Blocked unauthorized access from user_id={user_id}")
            if isinstance(event, Message):
                await event.answer(NO_ACCESS)
            elif isinstance(event, CallbackQuery):
                await event.answer(NO_ACCESS, show_alert=True)
            return
        return await handler(event, data)

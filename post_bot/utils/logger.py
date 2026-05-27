"""Loguru setup. Один вызов на процесс."""
from __future__ import annotations

import sys

from loguru import logger

from post_bot.config import get_settings

_configured = False


def setup_logger() -> None:
    global _configured
    if _configured:
        return
    s = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=s.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
        colorize=True,
    )
    _configured = True


__all__ = ["logger", "setup_logger"]

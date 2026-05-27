"""Inline keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def length_choice_kb() -> InlineKeyboardMarkup:
    """Выбор длины поста в начале брифа."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Короткий ~200", callback_data="length:200"),
        InlineKeyboardButton(text="Средний ~400", callback_data="length:400"),
    )
    kb.row(
        InlineKeyboardButton(text="Длинный ~600", callback_data="length:600"),
        InlineKeyboardButton(text="Авто", callback_data="length:auto"),
    )
    kb.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="brief:cancel"),
    )
    return kb.as_markup()


def brief_collecting_kb() -> InlineKeyboardMarkup:
    """Кнопки во время сбора брифа."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Готово, генерируй", callback_data="brief:generate"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="brief:cancel"),
    )
    return kb.as_markup()


def rating_kb(post_id: int) -> InlineKeyboardMarkup:
    """Inline-кнопки для оценки поста."""
    kb = InlineKeyboardBuilder()
    # Шкала: -10, -5, 0, +5, +7, +10 — достаточно для маркировки
    kb.row(
        InlineKeyboardButton(text="-10", callback_data=f"rate:{post_id}:-10"),
        InlineKeyboardButton(text="-5", callback_data=f"rate:{post_id}:-5"),
        InlineKeyboardButton(text="0", callback_data=f"rate:{post_id}:0"),
    )
    kb.row(
        InlineKeyboardButton(text="+5", callback_data=f"rate:{post_id}:5"),
        InlineKeyboardButton(text="+7", callback_data=f"rate:{post_id}:7"),
        InlineKeyboardButton(text="+10", callback_data=f"rate:{post_id}:10"),
    )
    kb.row(
        InlineKeyboardButton(text="💬 Комментарий", callback_data=f"comment:{post_id}"),
        InlineKeyboardButton(text="💾 В образцы", callback_data=f"save:{post_id}"),
    )
    kb.row(
        InlineKeyboardButton(text="🆕 Новый пост", callback_data="brief:new"),
    )
    return kb.as_markup()


def after_rating_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🆕 Новый пост", callback_data="brief:new"),
    )
    return kb.as_markup()

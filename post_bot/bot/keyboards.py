"""Inline keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ----------------------------- главное меню -----------------------------

def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню. Точка входа после /start и после каждого завершённого действия."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📝 Новый пост", callback_data="menu:new"))
    kb.row(InlineKeyboardButton(text="📚 Добавить пример", callback_data="menu:add_example"))
    kb.row(
        InlineKeyboardButton(text="📋 Мои правила", callback_data="menu:directives"),
        InlineKeyboardButton(text="📜 История", callback_data="menu:history"),
    )
    return kb.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Одна кнопка — возврат в главное меню."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home"))
    return kb.as_markup()


# ----------------------------- бриф (новый пост) -----------------------------

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
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"),
    )
    return kb.as_markup()


# ----------------------------- добавление примера -----------------------------

GENRES_RU = [
    ("introduction", "Представление"),
    ("contrarian_take", "Провокация"),
    ("numbered_lessons", "Нумерованный разбор"),
    ("personal_story", "Личная история"),
    ("tutorial", "Туториал/разбор"),
    ("announcement", "Анонс/новость"),
    ("news_comment", "Коммент к новости"),
]


def genre_choice_kb() -> InlineKeyboardMarkup:
    """Выбор жанра для загружаемого примера."""
    kb = InlineKeyboardBuilder()
    for code, label in GENRES_RU:
        kb.row(InlineKeyboardButton(text=label, callback_data=f"exgenre:{code}"))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:home"))
    return kb.as_markup()


def score_choice_kb() -> InlineKeyboardMarkup:
    """Выбор оценки для примера. 7 — порог попадания в активный пул."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="5", callback_data="exscore:5"),
        InlineKeyboardButton(text="6", callback_data="exscore:6"),
        InlineKeyboardButton(text="7", callback_data="exscore:7"),
    )
    kb.row(
        InlineKeyboardButton(text="8", callback_data="exscore:8"),
        InlineKeyboardButton(text="9", callback_data="exscore:9"),
        InlineKeyboardButton(text="10", callback_data="exscore:10"),
    )
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:home"))
    return kb.as_markup()

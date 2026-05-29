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
        InlineKeyboardButton(text="✅ Готово, показать сводку", callback_data="brief:done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="brief:cancel"),
    )
    return kb.as_markup()


def brief_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение брифа перед запуском генерации."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🚀 Генерировать", callback_data="brief:generate"),
        InlineKeyboardButton(text="← Назад (дополнить)", callback_data="brief:back"),
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
    ("reflection", "Рефлексия/мысль"),
    ("tutorial", "Туториал/разбор"),
    ("qa_explainer", "Вопрос-ответ (деловой)"),
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


def directives_list_kb(items: list[tuple[int, str, str, str | None]]) -> InlineKeyboardMarkup:
    """Список директив с кнопкой 🗑 у каждой + «➕ Добавить» сверху.
    items = [(id, polarity, text, genre_scope), ...]
    """
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Добавить правило", callback_data="directive:add"))
    for d_id, polarity, text, genre_scope in items:
        marker = "✅" if polarity == "do" else "🚫"
        scope = f" [{genre_scope[:3]}]" if genre_scope else ""
        # Длина callback'а ограничена 64 байтами — короткий id хватит.
        # Текст обрезаем для кнопки, полный показывается выше.
        preview = text if len(text) <= 36 else text[:34] + "…"
        kb.row(
            InlineKeyboardButton(
                text=f"{marker}{scope} {preview}  🗑",
                callback_data=f"directive:del:{d_id}",
            )
        )
    kb.row(InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"))
    return kb.as_markup()


def directive_polarity_kb() -> InlineKeyboardMarkup:
    """Шаг 2: DO / DON'T при добавлении правила вручную."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ DO (что делать)", callback_data="dpolarity:do"),
        InlineKeyboardButton(text="🚫 DON'T (не делать)", callback_data="dpolarity:dont"),
    )
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:home"))
    return kb.as_markup()


def directive_genre_kb() -> InlineKeyboardMarkup:
    """Шаг 3: глобальная или жанровая директива."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🌐 Глобально (на все посты)", callback_data="dgenre:global"))
    for code, label in GENRES_RU:
        kb.row(InlineKeyboardButton(text=f"🎯 {label}", callback_data=f"dgenre:{code}"))
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:home"))
    return kb.as_markup()


def confirm_delete_directive_kb(directive_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления."""
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"directive:confirm_del:{directive_id}"),
        InlineKeyboardButton(text="← Назад", callback_data="menu:directives"),
    )
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

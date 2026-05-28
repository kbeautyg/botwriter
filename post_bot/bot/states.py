"""FSM-состояния для брифинга."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BriefStates(StatesGroup):
    choosing_length = State()    # выбираем длину поста перед сбором брифа
    waiting = State()            # собираем текст и голосовые
    generating = State()         # pipeline работает
    awaiting_rating = State()    # ждём оценку и/или редактуру
    awaiting_comment = State()   # ждём текстовый комментарий к посту


class ExampleStates(StatesGroup):
    """Поток добавления стиль-примера руками."""
    waiting_text = State()       # ждём текст поста
    waiting_genre = State()      # ждём выбор жанра
    waiting_score = State()      # ждём выбор оценки


class DirectiveStates(StatesGroup):
    """Поток добавления директивы руками (не из комментария)."""
    entering_text = State()      # ждём текст правила
    choosing_polarity = State()  # DO / DON'T
    choosing_genre = State()     # глобально / конкретный жанр

"""FSM-состояния для брифинга."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BriefStates(StatesGroup):
    choosing_length = State()    # выбираем длину поста перед сбором брифа
    waiting = State()            # собираем текст и голосовые
    generating = State()         # pipeline работает
    awaiting_rating = State()    # ждём оценку и/или редактуру
    awaiting_comment = State()   # ждём текстовый комментарий к посту

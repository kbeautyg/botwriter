"""FSM-состояния для брифинга."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BriefStates(StatesGroup):
    waiting = State()       # собираем текст и голосовые
    generating = State()    # pipeline работает
    awaiting_rating = State()  # ждём оценку и/или редактуру

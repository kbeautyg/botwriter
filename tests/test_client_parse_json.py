"""Юнит-тест: парсинг JSON из ответа модели (markdown-обёртки, шум вокруг)."""
from __future__ import annotations

from post_bot.llm.client import ChatResult


def _res(text: str) -> ChatResult:
    return ChatResult(text=text, model="x", tokens_in=0, tokens_out=0, raw_finish="stop")


def test_parse_json_clean():
    r = _res('{"a": 1, "b": "ok"}')
    assert r.parse_json() == {"a": 1, "b": "ok"}


def test_parse_json_with_markdown_fence():
    r = _res('```json\n{"a": 1}\n```')
    assert r.parse_json() == {"a": 1}


def test_parse_json_with_prose_around():
    r = _res('Вот результат:\n{"score": 7, "note": "ok"}\nконец')
    assert r.parse_json() == {"score": 7, "note": "ok"}


def test_parse_json_broken_returns_empty():
    r = _res("not a json at all")
    assert r.parse_json() == {}

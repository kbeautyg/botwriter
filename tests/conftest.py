"""Pytest-фикстуры: пропуск LLM-тестов если нет OPENAI_API_KEY."""
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if not os.getenv("OPENAI_API_KEY"):
        skip_llm = pytest.mark.skip(reason="OPENAI_API_KEY not set")
        for item in items:
            if "llm" in item.keywords:
                item.add_marker(skip_llm)

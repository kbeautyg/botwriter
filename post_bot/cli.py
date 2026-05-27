"""CLI для smoke-теста без Telegram.

Использование:
    python -m post_bot.cli "Тезисы поста одной строкой или несколько строк"

или из stdin:
    cat brief.txt | python -m post_bot.cli -

Печатает сгенерированный пост + score + iterations.
"""
from __future__ import annotations

import asyncio
import sys

from post_bot.db.engine import get_session, init_db
from post_bot.db.repository import append_text, create_brief
from post_bot.pipeline.orchestrator import generate_post
from post_bot.utils.logger import setup_logger


async def _run(brief_text: str) -> None:
    setup_logger()
    await init_db()
    from data.seed import seed_if_empty
    await seed_if_empty()

    async with get_session() as s:
        brief = await create_brief(s, tg_user_id=0)
        await append_text(s, brief, brief_text)
        brief_id = brief.id

    result = await generate_post(brief_id)
    print()
    print("=" * 70)
    print(f"FINAL DRAFT · score={result.final_score:+.1f} · iter={result.iterations} · genre={result.post.genre}")
    print("=" * 70)
    print(result.final_draft.text)
    print("=" * 70)
    if len(result.history) > 1:
        print("\n--- История итераций ---")
        for i, (writer, critic) in enumerate(result.history):
            print(f"\niter {i}: score={critic.score}, markers={critic.ai_markers_found}")
            print(f"  feedback: {critic.feedback[:200]}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m post_bot.cli '<brief text>' | python -m post_bot.cli -")
        sys.exit(2)
    if sys.argv[1] == "-":
        brief = sys.stdin.read().strip()
    else:
        brief = " ".join(sys.argv[1:]).strip()
    if not brief:
        print("Empty brief.")
        sys.exit(2)
    asyncio.run(_run(brief))


if __name__ == "__main__":
    main()

"""Writer agent: тезисы + few-shot → черновик поста."""
from __future__ import annotations

from dataclasses import dataclass

from data.genre_rules import format_for_writer
from post_bot.config import get_settings
from post_bot.db.models import GoodPhrase, StyleExample
from post_bot.llm.client import chat
from post_bot.llm.planner import Plan
from post_bot.llm.prompts import WRITER_SYSTEM
from post_bot.utils.logger import logger


@dataclass
class WriterResult:
    draft: str
    genre: str
    reasoning: str
    tokens_in: int
    tokens_out: int
    model: str


def _format_examples(examples: list[StyleExample]) -> str:
    if not examples:
        return "(эталонов нет — опирайся только на описание голоса автора в инструкции)"
    blocks = []
    for i, ex in enumerate(examples, 1):
        blocks.append(
            f"--- ЭТАЛОН #{i} (жанр: {ex.genre}) ---\n"
            f"{ex.text}\n"
            f"--- /ЭТАЛОН #{i} ---"
        )
    return "\n\n".join(blocks)


def _format_good_phrases(phrases: list[GoodPhrase]) -> str:
    if not phrases:
        return "(пусто)"
    by_kind: dict[str, list[str]] = {}
    for p in phrases:
        by_kind.setdefault(p.kind, []).append(p.phrase)
    parts = []
    for kind, items in by_kind.items():
        parts.append(f"[{kind}] " + "; ".join(items[:15]))
    return "\n".join(parts)


def _format_directives(directives: list[tuple[str, str]]) -> str:
    if not directives:
        return "(пока пусто)"
    lines = []
    for text, polarity in directives:
        marker = "DO" if polarity == "do" else "DON'T"
        lines.append(f"  [{marker}] {text}")
    return "\n".join(lines)


def _build_user_prompt(
    *,
    brief_text: str,
    plan: Plan | None,
    examples: list[StyleExample],
    good_phrases: list[GoodPhrase],
    directives: list[tuple[str, str]] | None,
    genre_hint: str | None,
    critic_feedback: str | None,
    critic_must_fix: list[str] | None,
    previous_draft: str | None,
) -> str:
    sections: list[str] = []

    sections.append("═══ МАТЕРИАЛ АВТОРА (тезисы + расшифровки голосовых) ═══")
    sections.append(brief_text.strip() or "(пусто — это ошибка, оповести)")

    if plan is not None:
        sections.append("\n═══ ПЛАН ОТ РЕДАКТОРА (соблюдай) ═══")
        sections.append(plan.as_writer_block())
    elif genre_hint:
        sections.append(f"\n═══ ПОДСКАЗКА ПО ЖАНРУ ═══\nАвтор намекнул на жанр: {genre_hint}")

    # Жанровые правила — отдельным жирным блоком после плана
    effective_genre = (plan.genre if plan else genre_hint) or ""
    genre_block = format_for_writer(effective_genre)
    if genre_block:
        sections.append(f"\n{genre_block}")

    sections.append("\n═══ ЭТАЛОНЫ СТИЛЯ (так пишет Артём — подражай интонации, не копируй слова) ═══")
    sections.append(_format_examples(examples))

    sections.append(
        "\n═══ ХАРАКТЕРНАЯ ЛЕКСИКА АВТОРА (обязательно используй минимум 2 из этих оборотов) ═══"
    )
    sections.append(_format_good_phrases(good_phrases))

    if directives:
        sections.append(
            "\n═══ ДИРЕКТИВЫ АВТОРА (правила из его прошлых комментариев — обязательны) ═══"
        )
        sections.append(_format_directives(directives))

    if previous_draft and critic_feedback:
        sections.append("\n═══ ПРЕДЫДУЩАЯ ПОПЫТКА (которую критик завернул) ═══")
        sections.append(previous_draft.strip())
        sections.append("\n═══ FEEDBACK КРИТИКА (читай внимательно, переделай по сути) ═══")
        sections.append(critic_feedback.strip())
        if critic_must_fix:
            sections.append(
                "\nКОНКРЕТНЫЕ ФРАЗЫ К ПЕРЕПИСЫВАНИЮ (заменить или убрать):\n"
                + "\n".join(f"• {x}" for x in critic_must_fix)
            )

    sections.append(
        "\n═══ ЗАДАЧА ═══\n"
        "Напиши черновик поста в голосе Артёма. Длина — строго из плана ±10%. "
        "ОБЯЗАТЕЛЬНО:\n"
        "  • Используй минимум 2 характерных оборота автора.\n"
        "  • Включи минимум 1 колкую/самоироничную/жёсткую фразу.\n"
        "  • Концовка жалит или хукает — никакой нейтральной констатации.\n"
        "  • Соблюдай ВСЕ жанровые правила выше.\n"
        "  • Используй все must_keep_phrases из плана.\n"
        "Верни строгий JSON по формату из системной инструкции."
    )
    return "\n".join(sections)


async def write_draft(
    *,
    brief_text: str,
    plan: Plan | None = None,
    examples: list[StyleExample],
    good_phrases: list[GoodPhrase],
    directives: list[tuple[str, str]] | None = None,
    genre_hint: str | None = None,
    critic_feedback: str | None = None,
    critic_must_fix: list[str] | None = None,
    previous_draft: str | None = None,
) -> WriterResult:
    s = get_settings()
    user_prompt = _build_user_prompt(
        brief_text=brief_text,
        plan=plan,
        examples=examples,
        good_phrases=good_phrases,
        directives=directives,
        genre_hint=genre_hint,
        critic_feedback=critic_feedback,
        critic_must_fix=critic_must_fix,
        previous_draft=previous_draft,
    )
    logger.info(f"Writer: model={s.model_writer}, prompt_chars={len(user_prompt)}")
    res = await chat(
        model=s.model_writer,
        system=WRITER_SYSTEM,
        user=user_prompt,
        temperature=0.85,
        max_tokens=8000,  # для reasoning-моделей (gpt-5.x) важен большой бюджет
        json_mode=True,
    )
    payload = res.parse_json()
    draft = (payload.get("draft") or "").strip()
    if not draft:
        # Фолбэк: модель могла вернуть просто текст без JSON
        draft = res.text.strip()
        logger.warning("Writer: JSON пустой, использую raw text")
    genre = (payload.get("genre") or "unknown").strip()
    reasoning = (payload.get("reasoning") or "").strip()
    return WriterResult(
        draft=draft,
        genre=genre,
        reasoning=reasoning,
        tokens_in=res.tokens_in,
        tokens_out=res.tokens_out,
        model=s.model_writer,
    )

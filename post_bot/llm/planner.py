"""Planner agent: brief → структурный план поста (жанр, крючок, тезисы, тон, концовка).

Запускается первым в pipeline. Writer получает план как готовую раскладку и
фокусируется на голосе, а не на композиции.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from data.genre_rules import format_for_planner
from post_bot.config import get_settings
from post_bot.llm.client import chat
from post_bot.llm.prompts import PLANNER_SYSTEM
from post_bot.utils.logger import logger


@dataclass
class Plan:
    genre: str = "unknown"
    headline: str = ""           # звучный заголовок-провокация (отдельно от первой строки)
    hook: str = ""
    structure: str = ""
    opposition: str = ""         # против кого/чего пост (инфоцыгане, темщики, ленивые)
    we_position: str = ""        # позиция «мы» — кто такой автор/команда
    reader_filter: str = ""      # фраза отсева читателя («если у вас X — закройте пост»)
    key_points: list[str] = field(default_factory=list)
    must_keep_phrases: list[str] = field(default_factory=list)
    tone: str = "прямой"
    close_type: str = "strong_statement"
    close_announcement: str = "" # анонс следующего поста (если close_type=hook_next_post)
    length_words: int = 350
    rationale: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""

    def as_writer_block(self) -> str:
        """Форматирование плана для подкладки в Writer-промпт."""
        kp = "\n".join(f"  • {p}" for p in self.key_points) or "  (нет)"
        mk = "\n".join(f"  • {p}" for p in self.must_keep_phrases) or "  (нет)"
        opp = self.opposition or "(не задано — Writer обязан выбрать сам, без противника пост стерильный)"
        we = self.we_position or "(не задано — обозначь «мы» как команду с опытом)"
        rf = self.reader_filter or "(не задан — придумай фразу-отсев в стиле Артёма)"
        ann = self.close_announcement or "(не задан — придумай конкретный анонс)"
        return (
            f"ЖАНР: {self.genre}\n"
            f"ТОН: {self.tone}\n"
            f"ЦЕЛЕВАЯ ДЛИНА: {self.length_words} слов\n\n"
            f"🏆 ЗАГОЛОВОК ПОСТА (отдельная строка над текстом, используй точно):\n"
            f"  «{self.headline}»\n\n"
            f"⚔️ ПРОТИВНИК (кому/чему противопоставлен пост — обязательно упомяни):\n"
            f"  {opp}\n\n"
            f"👥 ПОЗИЦИЯ «МЫ» (кто говорит — команда автора с опытом):\n"
            f"  {we}\n\n"
            f"🚫 ОТСЕВ ЧИТАТЕЛЯ (одна фраза «лучше закройте этот пост, если…»):\n"
            f"  {rf}\n\n"
            f"ОТКРЫВАЮЩАЯ ФРАЗА-КРЮК (используй прямо или близко):\n  «{self.hook}»\n\n"
            f"СТРУКТУРА:\n  {self.structure}\n\n"
            f"КЛЮЧЕВЫЕ ТЕЗИСЫ (обязательно включи):\n{kp}\n\n"
            f"ФРАЗЫ АВТОРА К СОХРАНЕНИЮ (используй ЕСЛИ ЛОЖАТСЯ ЕСТЕСТВЕННО, иначе пропусти):\n{mk}\n\n"
            f"ТИП КОНЦОВКИ: {self.close_type}\n"
            f"  hook_next_post   — крючок на следующий пост (АНОНС: «{ann}»)\n"
            f"  direct_cta       — прямой призыв (ставь 🔥, включай уведомления)\n"
            f"  open_question    — открытый вопрос\n"
            f"  strong_statement — сильная финальная фраза без призыва"
        )


def _format_directives(directives: list[tuple[str, str]]) -> str:
    """directives: [(text, polarity), ...]"""
    if not directives:
        return "(нет — это первая итерация)"
    lines = []
    for text, polarity in directives:
        marker = "DO" if polarity == "do" else "DON'T"
        lines.append(f"  [{marker}] {text}")
    return "\n".join(lines)


async def plan_post(
    brief_text: str,
    *,
    target_length_words: int | None = None,
    directives: list[tuple[str, str]] | None = None,
) -> Plan:
    s = get_settings()
    sections = [
        "═══ МАТЕРИАЛ АВТОРА ═══",
        brief_text.strip(),
        "═══ /МАТЕРИАЛ ═══",
        "",
        format_for_planner(),
    ]
    if target_length_words:
        sections.append(
            f"\n═══ ЦЕЛЕВАЯ ДЛИНА ═══\n"
            f"Автор выбрал длину: ~{target_length_words} слов. "
            f"Поставь length_words ровно {target_length_words}, не отклоняйся больше чем на ±20%."
        )
    if directives:
        sections.append(
            "\n═══ ДИРЕКТИВЫ АВТОРА (из его прошлых комментариев) ═══\n"
            f"{_format_directives(directives)}\n"
            "Учитывай их при выборе тона, структуры, концовки."
        )
    sections.append(
        "\nСобери план поста по формату из системной инструкции. Строгий JSON.\n"
        "ВАЖНО: must_keep_phrases ОБЯЗАТЕЛЬНО должен содержать минимум 1-2 характерных "
        "оборота автора + одну колкую/самоироничную фразу — даже если в материале их нет, "
        "придумай подходящие в стиле автора."
    )
    user_prompt = "\n".join(sections)
    logger.info(f"Planner: model={s.model_critic} (cheap), brief_chars={len(brief_text)}")
    # Используем cheap-модель (та же что у Critic'а) — это структурное решение, не творчество
    res = await chat(
        model=s.model_critic,
        system=PLANNER_SYSTEM,
        user=user_prompt,
        temperature=0.5,
        max_tokens=1200,
        json_mode=True,
    )
    payload = res.parse_json()

    def _list(key: str) -> list[str]:
        v = payload.get(key) or []
        return [str(x).strip() for x in v if str(x).strip()]

    def _str(key: str, default: str = "") -> str:
        v = payload.get(key)
        return str(v).strip() if v else default

    def _int(key: str, default: int) -> int:
        v = payload.get(key)
        try:
            return max(150, min(800, int(v)))
        except (ValueError, TypeError):
            return default

    plan = Plan(
        genre=_str("genre", "unknown") or "unknown",
        headline=_str("headline"),
        hook=_str("hook"),
        structure=_str("structure"),
        opposition=_str("opposition"),
        we_position=_str("we_position"),
        reader_filter=_str("reader_filter"),
        key_points=_list("key_points"),
        must_keep_phrases=_list("must_keep_phrases"),
        tone=_str("tone", "прямой") or "прямой",
        close_type=_str("close_type", "strong_statement") or "strong_statement",
        close_announcement=_str("close_announcement"),
        length_words=_int("length_words", 350),
        rationale=_str("rationale"),
        tokens_in=res.tokens_in,
        tokens_out=res.tokens_out,
        model=s.model_critic,
    )
    logger.info(
        f"Planner: genre={plan.genre} tone={plan.tone} close={plan.close_type} "
        f"opposition='{plan.opposition[:40]}' headline='{plan.headline[:40]}' "
        f"key_points={len(plan.key_points)} must_keep={len(plan.must_keep_phrases)}"
    )
    return plan

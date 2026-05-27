"""Тексты сообщений бота. Вынесены чтобы тон легко правился."""
from __future__ import annotations


START = (
    "Привет. Это бот для черновиков постов.\n\n"
    "Как работать:\n"
    "1. Жми /new — начни новый бриф.\n"
    "2. Кидай тезисы текстом и/или голосовые — в любом порядке, сколько нужно.\n"
    "3. Когда всё сказал — нажми «Готово» под брифом или /done.\n"
    "4. Жди 20-40 сек, я соберу черновик в твоём стиле и покажу с баллом критика.\n"
    "5. Поставь оценку -10..+10. Если ≥ 7 — пост уходит в базу примеров для будущих генераций.\n\n"
    "Команды: /new — новый бриф · /done — собрать · /cancel — отмена · /history — последние посты"
)

NEW_BRIEF = (
    "Окей, новый бриф. Кидай тезисы текстом и/или голосовые.\n"
    "Когда закончишь — жми «Готово» ниже или /done."
)

ALREADY_COLLECTING = (
    "У тебя уже идёт бриф. Дополняй его или жми «Готово» / /done. "
    "Если хочешь начать заново — /cancel и потом /new."
)

NOT_IN_BRIEF = "Сначала открой бриф через /new."

GENERATING = "🔧 Собираю пост. 20-40 сек..."

VOICE_RECEIVED = "🎙 Голосовое принято. Расшифровываю..."
VOICE_TRANSCRIBED = "✍️ Расшифровка: «{preview}»"
VOICE_FAILED = "⚠️ Голосовое не расшифровалось: {err}"

TEXT_RECEIVED = "📝 Принял ({n_chars} симв.)"

CANCELLED = "Бриф отменён."

EMPTY_BRIEF = "Бриф пустой — кинь хотя бы что-то текстом или голосовым."

NO_ACCESS = "У тебя нет доступа к боту. Скажи Sharp'у свой TG user_id."

ERROR_GENERIC = "Что-то сломалось: {err}\nПопробуй ещё раз или /cancel + /new."


def render_post_header(score: float, iterations: int, genre: str | None) -> str:
    return (
        f"📄 Черновик готов\n"
        f"Жанр: {genre or '—'} · Критик: {score:+.1f} · Итераций: {iterations}"
    )


def render_rating_prompt() -> str:
    return "Оцени от -10 до +10:"


def render_rating_saved(rating: int, saved_to_examples: bool) -> str:
    line = f"✅ Оценка {rating:+d} записана."
    if saved_to_examples:
        line += " Пост ушёл в базу примеров — будущие генерации станут точнее."
    return line


def render_history(rows: list[tuple[int, str, int | None, str]]) -> str:
    """rows = [(post_id, genre, rating, text_preview), ...]"""
    if not rows:
        return "Постов пока нет."
    lines = ["📚 Последние посты:\n"]
    for post_id, genre, rating, preview in rows:
        r = f"{rating:+d}" if rating is not None else "—"
        lines.append(f"#{post_id} · {genre or '—'} · {r}\n  «{preview}»")
    return "\n\n".join(lines)

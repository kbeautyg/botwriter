"""Тексты сообщений бота. Вынесены чтобы тон легко правился."""
from __future__ import annotations


START = (
    "Привет. Это бот для черновиков постов.\n\n"
    "Как работать:\n"
    "1. Жми /new — начни новый бриф.\n"
    "2. Выбери длину поста.\n"
    "3. Кидай тезисы текстом и/или голосовые — в любом порядке, сколько нужно.\n"
    "4. Когда всё сказал — жми «Готово» или /done.\n"
    "5. Жди 20-40 сек, я соберу черновик и покажу с баллом критика.\n"
    "6. Поставь оценку или напиши комментарий 💬 (он научит меня для следующих постов).\n"
    "   Оценка ≥ 7 — пост уходит в базу примеров.\n\n"
    "Команды: /new · /done · /cancel · /history · /directives — что я запомнил"
)

LENGTH_PROMPT = (
    "Окей, новый бриф. Какой длины пост?"
)

NEW_BRIEF_AFTER_LENGTH = (
    "Длина: {length_label}.\n\n"
    "Кидай тезисы текстом и/или голосовые. Когда закончишь — жми «Готово» или /done."
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
    return (
        "Оцени от -10 до +10. "
        "Можешь также 💬 написать комментарий — я учту для следующих постов."
    )


COMMENT_PROMPT = (
    "Напиши, что не так / что хочешь иначе. "
    "Например: «слишком жёстко», «убери все эмодзи», «концовка не цепляет», "
    "«добавь больше цифр». Я разберу на правила и буду их учитывать в будущих постах."
)

COMMENT_SAVED = "✅ Учёл. В следующих постах буду этого придерживаться."


def render_length_chosen(length_words: int | None) -> str:
    if length_words is None:
        return "Авто (Planner сам выберет)"
    return f"~{length_words} слов"


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

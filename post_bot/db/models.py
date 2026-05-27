"""SQLAlchemy 2.0 модели. Async-friendly."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Brief(Base):
    """Заявка на пост — тезисы + транскрипты голосовых."""
    __tablename__ = "briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    voice_transcripts: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="collecting")
    # collecting | planning | generating | done | cancelled
    genre_hint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    drafts: Mapped[list["Draft"]] = relationship(
        back_populates="brief", cascade="all, delete-orphan", order_by="Draft.iteration"
    )

    @property
    def combined_input(self) -> str:
        chunks: list[str] = []
        if self.raw_text:
            chunks.append("ТЕЗИСЫ:\n" + self.raw_text.strip())
        if self.voice_transcripts:
            chunks.append(
                "ГОЛОСОВЫЕ (расшифровка):\n"
                + "\n---\n".join(t.strip() for t in self.voice_transcripts if t.strip())
            )
        return "\n\n".join(chunks).strip()


class Draft(Base):
    """Одна итерация генерации поста."""
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_id: Mapped[int] = mapped_column(ForeignKey("briefs.id", ondelete="CASCADE"), index=True)
    iteration: Mapped[int] = mapped_column(default=0)
    text: Mapped[str] = mapped_column(Text)

    writer_model: Mapped[str] = mapped_column(String(60))
    critic_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    critic_score: Mapped[float | None] = mapped_column(nullable=True)
    critic_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    critic_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_markers_found: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    must_fix: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)

    is_final: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    brief: Mapped["Brief"] = relationship(back_populates="drafts")


class Post(Base):
    """Финальный пост: тот draft что вернули юзеру, плюс его оценка/правка."""
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    brief_id: Mapped[int] = mapped_column(ForeignKey("briefs.id", ondelete="CASCADE"), index=True)
    final_draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"))

    text: Mapped[str] = mapped_column(Text)  # тот, что показали юзеру
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # если он переписал
    genre: Mapped[str | None] = mapped_column(String(40), nullable=True)

    user_rating: Mapped[int | None] = mapped_column(nullable=True)  # -10..+10
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    rated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    saved_as_example: Mapped[bool] = mapped_column(default=False)


class StyleExample(Base):
    """База примеров для few-shot. Сюда попадают seed-посты и одобренные пользователем."""
    __tablename__ = "style_examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    genre: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(20))  # seed | rated | manual
    score: Mapped[int] = mapped_column(default=10)  # для сортировки в retrieval
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    source_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )


class GoodPhrase(Base):
    """«Хорошие» обороты автора — извлечены стилистом из одобренных постов."""
    __tablename__ = "good_phrases"

    id: Mapped[int] = mapped_column(primary_key=True)
    phrase: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="phrase")  # phrase | structure | metaphor
    weight: Mapped[float] = mapped_column(default=1.0)
    source_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class BadPhrase(Base):
    """ИИ-маркеры и канцелярит, которые нужно избегать."""
    __tablename__ = "bad_phrases"

    id: Mapped[int] = mapped_column(primary_key=True)
    phrase: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="cliche")  # cliche | ai_marker | banned_word
    weight: Mapped[float] = mapped_column(default=1.0)
    source: Mapped[str] = mapped_column(String(20), default="seed")  # seed | learned
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

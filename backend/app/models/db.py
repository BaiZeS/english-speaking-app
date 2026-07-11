from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="k12")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book: Mapped[str] = mapped_column(String(16), index=True)
    lesson_no: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(256))
    role_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)

    history: Mapped[list["History"]] = relationship(back_populates="lesson")  # noqa: UP037


class History(Base):
    __tablename__ = "history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(Integer, ForeignKey("lessons.id"), index=True)
    line_id: Mapped[str] = mapped_column(String(64))
    audio_path: Mapped[str] = mapped_column(String(512))
    score_total: Mapped[float] = mapped_column(Float)
    score_pronunciation: Mapped[float] = mapped_column(Float)
    score_fluency: Mapped[float] = mapped_column(Float)
    score_completeness: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    lesson: Mapped["Lesson"] = relationship(back_populates="history")  # noqa: UP037

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", _uuid())
        kwargs.setdefault("created_at", _utcnow())
        super().__init__(**kwargs)


class TtsCache(Base):
    __tablename__ = "tts_cache"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    audio_path: Mapped[str] = mapped_column(String(512))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

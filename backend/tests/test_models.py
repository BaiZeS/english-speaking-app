from __future__ import annotations

from datetime import datetime

from app.models.db import History, Lesson, TtsCache, User


def test_user_columns() -> None:
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "device_id", "mode", "created_at"} <= cols


def test_lesson_columns() -> None:
    cols = {c.name for c in Lesson.__table__.columns}
    assert {"id", "book", "lesson_no", "title", "role_count", "duration_s"} <= cols


def test_history_columns() -> None:
    cols = {c.name for c in History.__table__.columns}
    assert {
        "id",
        "user_id",
        "lesson_id",
        "line_id",
        "audio_path",
        "score_total",
        "score_pronunciation",
        "score_fluency",
        "score_completeness",
        "created_at",
    } <= cols


def test_tts_cache_columns() -> None:
    cols = {c.name for c in TtsCache.__table__.columns}
    assert {"cache_key", "audio_path", "hit_count", "expires_at"} <= cols


def test_history_default_created_at_is_utc() -> None:
    h = History(
        user_id="00000000-0000-0000-0000-000000000000",
        lesson_id=1,
        line_id="L1",
        audio_path="x.m4a",
        score_total=80,
        score_pronunciation=80,
        score_fluency=80,
        score_completeness=80,
    )
    assert isinstance(h.created_at, datetime)
    assert h.created_at.tzinfo is not None

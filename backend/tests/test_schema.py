from __future__ import annotations

from app.models.schema import (
    HistoryItem,
    HistoryWriteRequest,
    LessonSummary,
    Line,
    Role,
    ScoreRequest,
    ScoreResponse,
    TtsResponse,
    WordScore,
)


def test_lesson_summary_fields() -> None:
    ls = LessonSummary(id=1, book="nce1", lesson_no=1, title="t", role_count=2, duration_s=10.0)
    assert ls.model_dump()["id"] == 1


def test_role_and_line() -> None:
    role = Role(name="A", lines=[Line(id="L1", text="hi", translation="嗨")])
    assert role.lines[0].id == "L1"


def test_score_request_accepts_audio_bytes() -> None:
    req = ScoreRequest(lesson_id=1, line_id="L1", ref_text="hi", mode="k12", audio=b"\x00\x01")
    assert req.audio[:2] == b"\x00\x01"


def test_score_request_category_defaults_to_read_sentence() -> None:
    req = ScoreRequest(lesson_id=1, line_id="L1", ref_text="hi", audio=b"\x00")
    assert req.category == "read_sentence"


def test_score_request_word_drill_without_lesson_context() -> None:
    """错词重练无课时上下文: lesson_id/line_id 可省略, category 用 read_word."""
    req = ScoreRequest(ref_text="schedule", category="read_word", audio=b"\x00\x01")
    assert req.lesson_id is None
    assert req.line_id is None
    assert req.category == "read_word"


def test_score_response_includes_word_details() -> None:
    r = ScoreResponse(
        total=80.0,
        pronunciation=82.0,
        fluency=78.0,
        completeness=80.0,
        word_details=[WordScore(word="hi", score=80, ipa="haɪ")],  # noqa: RUF001
        suggestion="ok",
    )
    assert r.word_details[0].word == "hi"


def test_tts_response_has_url_and_duration() -> None:
    t = TtsResponse(audio_url="https://x", duration_ms=1234)
    assert t.duration_ms == 1234


def test_history_write_request_round_trip() -> None:
    req = HistoryWriteRequest(
        device_id="dev",
        lesson_id=1,
        line_id="L1",
        audio_path="x.m4a",
        score_total=80,
        score_pronunciation=80,
        score_fluency=80,
        score_completeness=80,
    )
    assert req.model_dump()["device_id"] == "dev"


def test_history_item() -> None:
    h = HistoryItem(
        id="abc",
        lesson_id=1,
        line_id="L1",
        score_total=80.0,
        score_pronunciation=80.0,
        score_fluency=80.0,
        score_completeness=80.0,
        created_at="2026-07-11T00:00:00Z",
    )
    assert h.line_id == "L1"

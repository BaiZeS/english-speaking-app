from __future__ import annotations

import pytest

from app.scoring.read_along import score_read_along
from app.services.interfaces import AsrResult, AsrWord


def _asr(recognized: str, word_scores: list[AsrWord]) -> AsrResult:
    return AsrResult(recognized=recognized, word_scores=word_scores)


def test_perfect_reading_is_95() -> None:
    ref = "Hello world"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 95.0, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert res.total >= 95.0  # spec §testing acceptance: 完美发音 -> 95+
    assert res.pronunciation == 95.0
    assert res.fluency > 80
    assert res.completeness == 100.0


def test_completeness_drops_on_missing_words() -> None:
    ref = "Hello world friend"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(
            recognized="Hello world",
            word_scores=[AsrWord("Hello", 90, None), AsrWord("world", 90, None)],
        ),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert res.completeness == pytest.approx(200 / 3, abs=0.5)
    assert res.total < 80


def test_low_pronunciation_words_drag_total_down() -> None:
    ref = "Hello world"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(
            recognized=ref, word_scores=[AsrWord("Hello", 30, None), AsrWord("world", 30, None)]
        ),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert res.pronunciation == 30.0
    assert res.total < 60


def test_pause_count_penalizes_fluency() -> None:
    ref = "Hello world"
    clean = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 90, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    paused = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 90, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=5,
    )
    assert paused.fluency < clean.fluency


def test_word_details_preserve_order() -> None:
    ref = "Good morning everyone"
    res = score_read_along(
        ref_text=ref,
        asr=_asr(recognized=ref, word_scores=[AsrWord(w, 80, None) for w in ref.split()]),
        speech_rate_wpm=120.0,
        pause_count=0,
    )
    assert [w.word for w in res.word_details] == ref.split()

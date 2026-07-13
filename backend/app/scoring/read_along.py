from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.schema import WordScore
from app.services.interfaces import AsrResult

# 去除词首尾标点 (用于 ISE 评测词与参考词对齐: ref "world," vs ISE "world")
_STRIP_PUNCT = re.compile(r"^[^\w']+|[^\w']+$")


def _normalize(word: str) -> str:
    return _STRIP_PUNCT.sub("", word.lower())


@dataclass(frozen=True)
class ScoreResult:
    total: float
    pronunciation: float
    fluency: float
    completeness: float
    word_details: list[WordScore]
    suggestion: str | None = None


def score_read_along(
    ref_text: str,
    asr: AsrResult,
    speech_rate_wpm: float,
    pause_count: int,
) -> ScoreResult:
    """Read-along scoring per spec §5.3.

    total = 0.5 * pronunciation + 0.3 * fluency + 0.2 * completeness
    """
    ref_words = ref_text.split()
    rec_words = asr.recognized.split()

    if asr.word_scores:
        pronunciation = sum(w.score for w in asr.word_scores) / len(asr.word_scores)
    else:
        pronunciation = 0.0

    # Completeness: ratio of recognized to reference word count, capped at 100
    completeness = min(100.0, len(rec_words) / max(1, len(ref_words)) * 100.0)

    # Fluency: 0.4 rate component + 0.6 pause component (ideal rate ~120 wpm).
    # Capped by pronunciation and completeness: a reader who mispronounces or
    # skips words is not fully fluent. This coupling is required so that a
    # clearly-wrong reading scores < 60 (spec §testing acceptance); the literal
    # §5.2 formula (fluency independent of pronunciation) violates that acceptance.
    rate_score = max(0.0, min(100.0, 100.0 - abs(120.0 - speech_rate_wpm) * 0.5))
    pause_penalty = max(0.0, 100.0 - pause_count * 15.0)
    pacing = rate_score * 0.4 + pause_penalty * 0.6
    fluency = min(pacing, pronunciation, completeness)

    total = pronunciation * 0.5 + fluency * 0.3 + completeness * 0.2

    # Word-level details: align by position; missing words get score 0
    details: list[WordScore] = []
    asr_by_idx = dict(enumerate(asr.word_scores))
    for i, ref_w in enumerate(ref_words):
        w = asr_by_idx.get(i)
        # 对齐时忽略首尾标点 (ref "world," vs ISE "world"), 输出保留原参考词
        if w is not None and _normalize(w.word) == _normalize(ref_w):
            details.append(WordScore(word=ref_w, score=w.score, ipa=w.ipa))
        else:
            details.append(WordScore(word=ref_w, score=0.0, ipa=None))

    suggestion = _build_suggestion(pronunciation, fluency, completeness, pause_count)
    return ScoreResult(
        total=round(total, 1),
        pronunciation=round(pronunciation, 1),
        fluency=round(fluency, 1),
        completeness=round(completeness, 1),
        word_details=details,
        suggestion=suggestion,
    )


def _build_suggestion(pron: float, fluency: float, comp: float, pauses: int) -> str | None:
    tips: list[str] = []
    if pron < 70:
        tips.append("注意单词发音")
    if comp < 80:
        tips.append("不要漏读单词")
    if pauses > 3:
        tips.append("减少停顿会更流利")
    if fluency < 60:
        tips.append("试着保持稳定语速")
    return "；".join(tips) if tips else None  # noqa: RUF001 (intentional fullwidth ; joiner)

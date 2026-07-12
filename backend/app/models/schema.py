from __future__ import annotations

from pydantic import BaseModel, Field

# ====== Lessons ======


class LessonSummary(BaseModel):
    id: int
    book: str
    lesson_no: int
    title: str
    role_count: int
    duration_s: float


class Line(BaseModel):
    id: str
    text: str
    translation: str | None = None
    ipa: str | None = None


class Role(BaseModel):
    name: str
    lines: list[Line]


class LessonDetail(BaseModel):
    id: int
    book: str
    lesson_no: int
    title: str
    roles: list[Role]


# ====== TTS ======


class TtsResponse(BaseModel):
    audio_url: str
    duration_ms: int


# ====== Score ======


class WordScore(BaseModel):
    word: str
    score: float = Field(ge=0, le=100)
    ipa: str | None = None


class ScoreRequest(BaseModel):
    lesson_id: int
    line_id: str = Field(max_length=64)
    ref_text: str = Field(max_length=2000)
    mode: str = "k12"
    audio: bytes = Field(max_length=10_000_000)


class ScoreResponse(BaseModel):
    total: float = Field(ge=0, le=100)
    pronunciation: float = Field(ge=0, le=100)
    fluency: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=100)
    word_details: list[WordScore]
    suggestion: str | None = None


# ====== History ======


class HistoryWriteRequest(BaseModel):
    device_id: str = Field(max_length=128)
    lesson_id: int
    line_id: str = Field(max_length=64)
    audio_path: str = Field(max_length=512)
    score_total: float = Field(ge=0, le=100)
    score_pronunciation: float = Field(ge=0, le=100)
    score_fluency: float = Field(ge=0, le=100)
    score_completeness: float = Field(ge=0, le=100)


class HistoryItem(BaseModel):
    id: str
    lesson_id: int
    line_id: str
    score_total: float
    score_pronunciation: float
    score_fluency: float
    score_completeness: float
    created_at: str

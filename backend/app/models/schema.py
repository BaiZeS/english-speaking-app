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
    # 音源标记: "mimo"=MiMo TTS, "stub"=本地占位假音频.
    # 前端可据此判断是否真实语音 (避免 stub 音频被当成自然语音播放).
    # 旧客户端不读此字段也兼容 (向后兼容新增字段).
    source: str = "stub"


# ====== Score ======


class WordScore(BaseModel):
    word: str
    score: float = Field(ge=0, le=100)
    ipa: str | None = None


class ScoreRequest(BaseModel):
    # lesson_id/line_id 可选: 错词重练 (单词 drill) 没有课时上下文.
    lesson_id: int | None = None
    line_id: str | None = Field(default=None, max_length=64)
    ref_text: str = Field(max_length=2000)
    mode: str = "k12"
    # ISE 评测类型: "read_sentence" (跟读句子) 或 "read_word" (单词重练).
    category: str = Field(default="read_sentence", max_length=32)
    audio: bytes = Field(max_length=10_000_000)


class ScoreResponse(BaseModel):
    total: float = Field(ge=0, le=100)
    pronunciation: float = Field(ge=0, le=100)
    fluency: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=100)
    word_details: list[WordScore]
    suggestion: str | None = None
    # 评分来源: "xunfei"=真实讯飞 ISE, "stub"=占位假分 (未配凭据/调用失败).
    # 前端据此提示用户当前分数不是真实评测. 旧客户端不读此字段也兼容.
    source: str = "stub"


# ====== History ======


class HistoryWriteRequest(BaseModel):
    device_id: str = Field(max_length=128)
    # 旧客户端不传 book 时按新概念一册兜底 (历史上只有这一本书).
    book: str = Field(default="nce1", max_length=32)
    lesson_id: int
    line_id: str = Field(max_length=64)
    audio_path: str = Field(max_length=512)
    score_total: float = Field(ge=0, le=100)
    score_pronunciation: float = Field(ge=0, le=100)
    score_fluency: float = Field(ge=0, le=100)
    score_completeness: float = Field(ge=0, le=100)


class HistoryItem(BaseModel):
    id: str
    book: str = "nce1"
    lesson_id: int
    line_id: str
    #: P8 §5.7: 行种类 — "lesson" (课本四模式) | "scene_course" (情景课实战收工).
    #: add-only, 旧客户端不读不受影响.
    kind: str = "lesson"
    #: 人读标题: 情景课行为「课名 · 实战对话」, 课本行沿用 line_id.
    label: str = ""
    score_total: float
    score_pronunciation: float
    score_fluency: float
    score_completeness: float
    created_at: str

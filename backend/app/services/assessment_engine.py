"""CEFR 摸底测评引擎 (计划 §5.2 M3 / §5.5-3 / §七 P4).

题库 (``data/assessment/bank.json``, 7 题人工编写零 LLM) -> start/answer 只做
落库与转写, **判级集中在 complete 一次批量 LLM 调用** (§四 决策表: 7 题 x 20s
逐题判会把「5 分钟测评」拖爆)。

诚实边界 (§5.6 门控在测评上的投影):

* **发音维只取真实 ISE** —— 跟读题音频过了真 ISE 才把分存进
  ``assessment_answers.ise_score``; 讯飞没配时 StubASR 恒 95 是占位, **不落库**,
  发音维保持 null (宁缺勿滥, 与 mission 的锚定 ISE 同一条纪律);
* **判级 LLM 不可用 -> source="stub"**: 结果照常返回但 cefr/语法/词汇/流利全 null
  + 中文说明, **零事件、零画像写入** (诚实空态) —— 本机画像「纹丝不动」是功能;
* 真 LLM 判级才写画像: ``ability_events`` (``source_kind="assessment"``, w=1,
  **alpha=0.6** 重拉 —— 测评是专程的一次性测量) + ``assessment_cefr`` +
  ``band_locked=True`` + ``cefr_level=resolve_level(...)`` (±1 band 锁, 口径在
  ``ability_engine``, 不造第二套映射)。

题库根 (``_BANK_ROOT``) 是模块常量, 测试 monkeypatch 换目录 (仿 T2 scene_store);
单个坏文件只让题库变空 + warning, 不打死端点 (T2 跳过策略)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.models.db import AssessmentAnswer
from app.services.ability_engine import CEFR_ORDER
from app.services.drill_grader import (
    ANSWER_MAX_CHARS,
    LlmUnavailableError,
    _judge,
    _resolve_judge_model,
)
from app.services.llm_provider import LlmMessage

logger = logging.getLogger(__name__)

#: 题库根目录 (backend/data); 测试 monkeypatch 这个常量换目录.
_BANK_ROOT: Path = Path(__file__).resolve().parent.parent.parent / "data"

BANK_DIR_NAME = "assessment"
BANK_FILE_NAME = "bank.json"

#: 测评判级的 EWMA 步长覆写 (§四/T5 任务书: 一次性专程测量, 重拉 alpha=0.6).
ASSESSMENT_ALPHA = 0.6

#: 判级批量调用的输出预算 (一次喂全部转写).
JUDGE_MAX_TOKENS = 600

QuestionType = Literal["read_aloud", "retell", "translate", "open_question", "quick_chat"]


class AssessmentQuestion(BaseModel):
    """题库一题 (完整形状; 客户端摘要只投影无答案字段)."""

    id: str = Field(min_length=1, max_length=32)
    no: int = Field(ge=1, le=99)
    type: QuestionType
    cefr_anchor: str
    cn_prompt: str = Field(min_length=1, max_length=500)
    ref_text: str = Field(min_length=1, max_length=2000)
    translation_cn: str = Field(default="", max_length=1000)
    key_points: list[str] = Field(min_length=1, max_length=12)
    seconds: int = Field(default=30, ge=5, le=300)

    @property
    def display_text(self) -> str:
        """给学员看的题目本体 (跟读句/复述材料/中文原句/问题本身)."""
        return self.ref_text


class Judgement(BaseModel):
    """判级 LLM 的输出契约 (§5.5-3: cefr + 三维 + 中文理由)."""

    cefr: str
    grammar: float = Field(ge=0, le=100)
    vocabulary: float = Field(ge=0, le=100)
    fluency: float = Field(ge=0, le=100)
    rationale_cn: str = Field(min_length=1, max_length=2000)

    @field_validator("cefr")
    @classmethod
    def _check_cefr(cls, v: str) -> str:
        # 不在 A1..C2 里 = 输出不合规 -> _judge 回喂重试 (校验错误喂回模型).
        if v not in CEFR_ORDER:
            raise ValueError(f"cefr must be one of {list(CEFR_ORDER)}")
        return v


# ====== 题库读路径 (T2 跳过策略: 坏文件 -> 空题库 + warning) ======


def _bank_file() -> Path:
    return _BANK_ROOT / BANK_DIR_NAME / BANK_FILE_NAME


def load_bank() -> list[AssessmentQuestion]:
    """全部测评题 (每次现读: 7 题小文件, 不设 TTL 免得测试 monkeypatch 泄漏)."""
    path = _bank_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("bank.json must contain a JSON object")
        questions_raw = raw.get("questions")
        if not isinstance(questions_raw, list):
            raise ValueError("bank.json needs a questions array")
        questions = [AssessmentQuestion.model_validate(item) for item in questions_raw]
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("assessment bank skipped (%s): %s", path.name, exc)
        return []
    questions.sort(key=lambda q: q.no)
    if len({q.no for q in questions}) != len(questions):
        logger.warning("assessment bank has duplicate question numbers; keeping first")
        seen: set[int] = set()
        unique: list[AssessmentQuestion] = []
        for question in questions:
            if question.no not in seen:
                seen.add(question.no)
                unique.append(question)
        questions = unique
    return questions


def question_by_no(questions: list[AssessmentQuestion], no: int) -> AssessmentQuestion | None:
    return next((q for q in questions if q.no == no), None)


# ====== 判级 prompt (§5.5-3: 一次批量) ======


def judge_messages(facts: list[dict[str, str]], pronunciation_note: str) -> list[LlmMessage]:
    """把全部作答 + 参考要点 + 发音维证据一次喂给考官 LLM.

    ``facts`` 每项: {no, type, anchor, prompt, answer, key_points, ise} —— ``answer``
    为空串表示该题未作答 (不虚构, 让考官按「未作答」降分)。
    """
    blocks: list[str] = []
    for fact in facts:
        answer = fact["answer"] or "(未作答)"
        blocks.append(
            f"第{fact['no']}题 [{fact['type']} | 难度锚 {fact['anchor']}] {fact['prompt']}\n"
            f"学员作答: {answer}\n参考要点: {fact['key_points']}{fact['ise']}"
        )
    system = (
        "你是 CEFR 口语定级考官, 学员是中文母语的企业管理者: 读写强、开口少。"
        "这是一次 5 分钟摸底测评的全部作答 (文本作答或语音转写)。"
        "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。\n"
        "判级口径: 题目按 A2-B1 梯度设计 —— 能完成全部 A2 题且 B1 题大体达意 = B1; "
        "A2 题基本达意 = A2; 多数题未作答或答非所问 = A1; "
        "全部题达意且表达自然少错可到 B2。\n"
        "grammar / vocabulary / fluency 是 0-100 的分项估计 (语法准确性 / 词汇范围与准确度 "
        "/ 流利度与语速), 必须有区分度, 不给虚高分。\n"
        "rationale_cn 用 3-5 句简体中文: 先给定级结论, 再逐维一句话依据, 最后一条最该练什么。"
    )
    user = "\n\n".join(blocks) + (f"\n\n{pronunciation_note}" if pronunciation_note else "")
    return [LlmMessage(role="system", content=system), LlmMessage(role="user", content=user)]


async def judge_level(
    facts: list[dict[str, str]], pronunciation_note: str
) -> tuple[Judgement, str] | None:
    """一次批量判级; 返回 ``(judgement, llm_source)``; LLM 不可用 -> ``None`` (诚实空态)."""
    try:
        judgement = await _judge(
            Judgement, judge_messages(facts, pronunciation_note), max_tokens=JUDGE_MAX_TOKENS
        )
    except LlmUnavailableError as exc:
        logger.warning("assessment judging unavailable | reason=%s", exc)
        return None
    return judgement, _resolve_judge_model()


def pronunciation_evidence(answers: list[AssessmentAnswer]) -> tuple[float | None, int]:
    """真实 ISE 发音维证据: ``(均分, 题数)``; 没有真实 ISE 行 -> ``(None, 0)``.

    ``ise_score`` 列在 answer 端点就只存真实 ISE (stub 占位分不落库), 这里直接聚合。
    """
    scores = [float(a.ise_score) for a in answers if a.ise_score is not None]
    if not scores:
        return None, 0
    return round(sum(scores) / len(scores), 1), len(scores)


def ability_events_from_judgement(
    judgement: Judgement | None, pronunciation: float | None
) -> list[tuple[str, float]]:
    """判级结果 -> §5.6 维度证据 ``(dimension, score)`` 列表 (仅真判级时非空).

    发音维**只有**真实 ISE 均分才产事件; 语法/词汇/流利来自 LLM 判级。调用方把
    ``source_kind="assessment"`` / w=1 / alpha=0.6 交给 ``ability_engine.record_step_evidence``。
    """
    if judgement is None:
        return []
    events: list[tuple[str, float]] = [
        ("grammar", judgement.grammar),
        ("vocabulary", judgement.vocabulary),
        ("fluency", judgement.fluency),
    ]
    if pronunciation is not None:
        events.append(("pronunciation", pronunciation))
    return events


def truncate_answer(text: str) -> str:
    """作答文本的落库上限 (与 drill 的 ANSWER_MAX_CHARS 同一口径)."""
    return text.strip()[:ANSWER_MAX_CHARS]


__all__ = [
    "ASSESSMENT_ALPHA",
    "AssessmentQuestion",
    "Judgement",
    "ability_events_from_judgement",
    "judge_level",
    "load_bank",
    "pronunciation_evidence",
    "question_by_no",
    "truncate_answer",
]

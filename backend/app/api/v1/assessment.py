"""CEFR 摸底测评端点 (计划 §5.3 / §5.5-3, 阶段 P4).

==============================================  =================================================
``GET  /assessment``                            题库摘要 (题目本体下发, 参考要点不下发)
``POST /assessment/start``                      开一次测评 -> attempt 行 + 题目列表
``POST /assessment/{attempt_id}/answer``        逐题作答 (文本直给; 音频走 IAT/ISE)
``POST /assessment/{attempt_id}/complete``      一次批量 LLM 判级 -> CEFR + 三维 + 画像写入
==============================================  =================================================

门禁语义: attempt 归属看 ``user_id`` (别人的 403, 不存在的 404); 已完成的 attempt
``complete`` 幂等返回已存结果, ``answer`` 则 409 ``ATTEMPT_NOT_ACTIVE``。

判级诚实边界见 ``assessment_engine`` 模块 docstring (stub 零事件零画像;
发音维只取真实 ISE)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.course import FoundationStep
from app.models.db import AssessmentAnswer, AssessmentAttempt, User
from app.services import ability_engine, assessment_engine
from app.services.ability_engine import DIMENSIONS
from app.services.assessment_engine import (
    ASSESSMENT_ALPHA,
    AssessmentQuestion,
    Judgement,
)
from app.services.audio_input import decode_audio
from app.services.drill_grader import (
    ANSWER_MAX_CHARS,
    AbilityEvidence,
    Dimension,
    grade_read_along,
    transcribe_audio,
)
from app.services.users import lookup_user

router = APIRouter(tags=["assessment"])


class _Identity(BaseModel):
    """``device_id`` / ``user_id`` 二选一 (与 course_sessions 同一口径)."""

    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=36)


# ====== 题库摘要 / 开考 ======


class QuestionSummary(BaseModel):
    """下发到客户端的一题 (key_points / 参考答案**永不**下发)."""

    id: str
    no: int
    type: str
    cefr_anchor: str
    cn_prompt: str
    display_text: str
    translation_cn: str = ""
    seconds: int


class BankSummary(BaseModel):
    total: int
    questions: list[QuestionSummary]


def _summaries(questions: list[AssessmentQuestion]) -> list[QuestionSummary]:
    return [
        QuestionSummary(
            id=q.id,
            no=q.no,
            type=q.type,
            cefr_anchor=q.cefr_anchor,
            cn_prompt=q.cn_prompt,
            display_text=q.display_text,
            translation_cn=q.translation_cn,
            seconds=q.seconds,
        )
        for q in questions
    ]


@router.get("/assessment", response_model=BankSummary)
async def get_bank() -> BankSummary:
    """题库摘要: 题型/题干/题目本体 + 建议用时 (零身份要求, 测评引导页直接渲染)."""
    questions = assessment_engine.load_bank()
    return BankSummary(total=len(questions), questions=_summaries(questions))


class StartResponse(BankSummary):
    """``POST /assessment/start`` 的载荷: attempt id + 同一份题目列表."""

    attempt_id: str


@router.post("/assessment/start", status_code=201, response_model=StartResponse)
async def start_assessment(
    req: _Identity,
    db: AsyncSession = Depends(get_db),
) -> StartResponse:
    """开一次测评: 建 attempt 行 (running), 返回题库摘要.

    题目清单每次全量下发 (7 题), 客户端自己翻页; 逐题作答按 ``question_no`` 提交。
    """
    user = await _resolve_user(db, req)
    attempt = AssessmentAttempt(user_id=user.id, status="running")
    db.add(attempt)
    await db.commit()
    questions = assessment_engine.load_bank()
    if not questions:
        # 题库坏了 (部署不完整) —— 宁可 500 前给明确错误, 不发一张空卷.
        raise AppError(503, "assessment bank is unavailable", "ASSESSMENT_BANK_UNAVAILABLE")
    logger.info("assessment started | attempt={} user={}", attempt.id, user.id)
    return StartResponse(
        attempt_id=attempt.id, total=len(questions), questions=_summaries(questions)
    )


# ====== 逐题作答 ======


class AnswerRequest(_Identity):
    question_no: int = Field(ge=1, le=99)
    #: 文本作答 (开放问答/翻译/快答主路径).
    text: str | None = Field(default=None, max_length=ANSWER_MAX_CHARS)
    #: PCM L16 16kHz mono base64 (跟读题走 ISE; 其余题型走 IAT 转写).
    audio_b64: bytes | None = Field(default=None, max_length=14_000_000)


class AnswerResponse(BaseModel):
    attempt_id: str
    question_no: int
    answers_count: int
    total: int
    #: 本次落库的作答文本 (ISE stub 时为空 —— 没有真转写就没有证据).
    transcript: str = ""


@router.post("/assessment/{attempt_id}/answer", response_model=AnswerResponse)
async def submit_answer(
    attempt_id: str,
    req: AnswerRequest,
    db: AsyncSession = Depends(get_db),
) -> AnswerResponse:
    """逐题作答: 文本直给; 音频按题型走 ISE (跟读) 或 IAT 转写 (其余).

    转写不出 (讯飞没配) -> 400 ``TRANSCRIPT_UNAVAILABLE`` —— 与 drill/mission 同一
    语义: **没有转写就没有证据**, 不拿占位分冒充口语作答。
    """
    attempt = await _load_owned_attempt(db, attempt_id, req)
    if attempt.status != "running":
        raise AppError(409, "this assessment attempt is already completed", "ATTEMPT_NOT_ACTIVE")
    question = assessment_engine.question_by_no(assessment_engine.load_bank(), req.question_no)
    if question is None:
        raise AppError(404, f"question {req.question_no} not found", "QUESTION_NOT_FOUND")

    text = (req.text or "").strip()
    audio_bytes = decode_audio(req.audio_b64 or b"")
    transcript = ""
    ise_score: float | None = None
    wpm: float | None = None
    if not text and not audio_bytes:
        raise AppError(
            400, f"question {question.no} needs text or audio", "ASSESSMENT_ANSWER_REQUIRED"
        )
    if question.type == "read_aloud" and audio_bytes:
        # 跟读题: 过一遍 ISE 管线; **真实 ISE 才落分** (stub 恒 95 不落库, 发音维宁缺勿滥).
        grade = await grade_read_along(_pseudo_step(question), audio_bytes)
        if grade.source == "xunfei":
            ise_score = grade.pronunciation
            wpm = grade.speech_rate_wpm
            transcript = grade.transcript or ""
    elif audio_bytes:
        # 其余题型: 音频必须先转写 (IAT 无 stub).
        transcript = (await transcribe_audio(audio_bytes) or "").strip()
        if not transcript:
            raise AppError(
                400,
                "音频无法转写 (讯飞 IAT 未配置), 请改用 text 作答",
                "TRANSCRIPT_UNAVAILABLE",
            )
    if text:
        transcript = text.strip()[:ANSWER_MAX_CHARS]

    row = (
        await db.execute(
            select(AssessmentAnswer).where(
                AssessmentAnswer.attempt_id == attempt.id,
                AssessmentAnswer.question_no == question.no,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AssessmentAnswer(
            attempt_id=attempt.id,
            question_no=question.no,
            transcript=assessment_engine.truncate_answer(transcript) if transcript else "",
            ise_score=ise_score,
            speech_rate_wpm=wpm,
        )
        db.add(row)
    else:
        # 重答覆盖 (唯一索引 attempt+question 的另一半语义).
        row.transcript = assessment_engine.truncate_answer(transcript) if transcript else ""
        row.ise_score = ise_score
        row.speech_rate_wpm = wpm
    await db.commit()
    count = await _answers_count(db, attempt.id)
    return AnswerResponse(
        attempt_id=attempt.id,
        question_no=question.no,
        answers_count=count,
        total=len(assessment_engine.load_bank()),
        transcript=row.transcript,
    )


def _pseudo_step(question: AssessmentQuestion) -> FoundationStep:
    """跟读题 -> ISE 评分器的输入 (复用 /score 的完整管线, 含 stub 标记)."""
    return FoundationStep(
        id=f"a{question.no}",
        type="read_along",
        cn_prompt=question.cn_prompt,
        ref_text=question.ref_text,
        translation_cn=question.translation_cn,
    )


# ====== 判级收口 ======


class RadarAxisDto(BaseModel):
    dimension: str
    score: float | None
    max: float = 100.0
    n: int = 0


class CompleteResponse(BaseModel):
    """``complete`` 的载荷 (存 ``attempt.result``, 幂等重放同形状)."""

    attempt_id: str
    status: str = "completed"
    #: 权威定级 (stub 判级时为 null —— 未判级就是未判级).
    cefr: str | None = None
    #: 4 维分 (null = 该维没有可信证据; 发音维只取真实 ISE).
    dims: dict[str, float | None] = Field(default_factory=dict)
    radar: list[RadarAxisDto] = Field(default_factory=list)
    rationale_cn: str = ""
    #: "ise" = 发音分来自真实 ISE; null = 没有真实发音证据.
    pronunciation_source: str | None = None
    #: llm = 真判级 (已写画像); stub = LLM 未配置 (零写入, 诚实空态).
    source: str
    llm_source: str | None = None
    #: 判级写入后的权威徽章值 (resolve_level, ±1 band 锁后); stub 恒 null.
    cefr_level: str | None = None


class CompleteRequest(_Identity):
    pass


@router.post("/assessment/{attempt_id}/complete", response_model=CompleteResponse)
async def complete_assessment(
    attempt_id: str,
    req: CompleteRequest,
    db: AsyncSession = Depends(get_db),
) -> CompleteResponse:
    """收卷: **一次批量** LLM 判级 (§5.5-3) -> CEFR + 三维 + rationale.

    写入门控 (T5 任务书): 真判级才写 ``ability_profiles`` (alpha=0.6 种子/重拉) +
    ``ability_events`` (``source_kind="assessment"``, w=1) + ``assessment_cefr`` +
    ``band_locked=True``; LLM 不可用 -> 结果照常返回但全部维度 null + 零写入。
    """
    attempt = await _load_owned_attempt(db, attempt_id, req)
    if attempt.status == "completed" and isinstance(attempt.result, dict):
        # 幂等: 客户端重试/断线重连直接回放已存结果.
        return CompleteResponse.model_validate(dict(attempt.result))

    answers = list(
        (
            await db.execute(
                select(AssessmentAnswer)
                .where(AssessmentAnswer.attempt_id == attempt.id)
                .order_by(AssessmentAnswer.question_no.asc())
            )
        ).scalars()
    )
    if not answers:
        raise AppError(400, "no answers submitted for this attempt", "ASSESSMENT_NO_ANSWERS")
    questions = assessment_engine.load_bank()

    pronunciation, ise_n = assessment_engine.pronunciation_evidence(answers)
    facts = _judge_facts(questions, answers)
    note = (
        f"发音维证据: {ise_n} 道跟读题有真实 ISE 分, 均分 {pronunciation}。"
        if pronunciation is not None
        else "发音维证据: 没有真实 ISE 分 (外部评测未配置), 请不要虚构发音分。"
    )
    judged = await assessment_engine.judge_level(facts, note)

    if judged is None:
        # 诚实空态: LLM 未配置/两次输出都不合规 -> 零事件、零画像、cefr=null.
        result = CompleteResponse(
            attempt_id=attempt.id,
            cefr=None,
            dims={dim: (pronunciation if dim == "pronunciation" else None) for dim in DIMENSIONS},
            radar=[
                RadarAxisDto(
                    dimension=dim,
                    score=pronunciation if dim == "pronunciation" else None,
                    n=ise_n if dim == "pronunciation" else 0,
                )
                for dim in DIMENSIONS
            ],
            rationale_cn="LLM 未配置或输出不可用, 本次没有判级。分维度都为空, 不计入能力画像。",
            pronunciation_source="ise" if pronunciation is not None else None,
            source="stub",
            llm_source="stub",
            cefr_level=None,
        )
    else:
        judgement, llm_source = judged
        result = await _write_judged_profile(
            db, attempt, judgement, llm_source, pronunciation, ise_n
        )

    attempt.status = "completed"
    attempt.finished_at = datetime.now(UTC)
    attempt.result = result.model_dump(mode="json")
    await db.commit()
    logger.info(
        "assessment completed | attempt={} source={} cefr={}",
        attempt.id,
        result.source,
        result.cefr,
    )
    return result


def _judge_facts(
    questions: list[AssessmentQuestion], answers: list[AssessmentAnswer]
) -> list[dict[str, str]]:
    """作答 + 题库 -> 判级 prompt 的逐题 facts (题目按 no 对齐, 没作答的题标未作答)."""
    by_no = {a.question_no: a for a in answers}
    facts: list[dict[str, str]] = []
    for question in questions:
        answer = by_no.get(question.no)
        ise_note = ""
        if answer is not None and answer.ise_score is not None:
            ise_note = f" | 真实 ISE 发音分: {answer.ise_score}"
        facts.append(
            {
                "no": str(question.no),
                "type": question.type,
                "anchor": question.cefr_anchor,
                "prompt": question.cn_prompt,
                "answer": (answer.transcript if answer is not None else "") or "",
                "key_points": "; ".join(question.key_points),
                "ise": ise_note,
            }
        )
    return facts


async def _write_judged_profile(
    db: AsyncSession,
    attempt: AssessmentAttempt,
    judgement: Judgement,
    llm_source: str,
    pronunciation: float | None,
    ise_n: int,
) -> CompleteResponse:
    """真判级: 事件流水 (source_kind=assessment, w=1, alpha=0.6) + 画像 + CEFR 写入门.

    ``record_step_evidence`` 不 commit —— 与 attempt.result 的落库同事务 (端点 commit)。
    """
    events = [
        AbilityEvidence(
            dimension=cast(Dimension, dimension),
            score=score,
            source="assessment",
            weight=1.0,
            # 发音事件带参考口径 (真实 ISE = 有标准答案的跟读题), 其余维度不带.
            ise_ref_mode="exact_reference" if dimension == "pronunciation" else None,
        )
        for dimension, score in assessment_engine.ability_events_from_judgement(
            judgement, pronunciation
        )
    ]
    await ability_engine.record_step_evidence(
        db,
        user_id=attempt.user_id,
        # step_id 列宽 32: attempt id 是 36 字符 uuid, 截前 20 位拼前缀刚好放下.
        step_id=f"assessment:{attempt.id[:20]}",
        evidence=events,
        alpha=ASSESSMENT_ALPHA,
    )
    profile = await ability_engine.get_profile(db, attempt.user_id)
    cefr_level: str | None = None
    if profile is not None:
        # §5.6/T4 口径: assessment_cefr 是权威锚; band_locked 后四维映射最多 ±1 band.
        profile.assessment_cefr = judgement.cefr
        profile.band_locked = True
        profile.cefr_level = ability_engine.resolve_level(
            assessment=judgement.cefr,
            derived=ability_engine.derived_level(
                {
                    "pronunciation": profile.pronunciation,
                    "grammar": profile.grammar,
                    "vocabulary": profile.vocabulary,
                    "fluency": profile.fluency,
                }
            ),
            band_locked=True,
        )
        cefr_level = profile.cefr_level
    dims: dict[str, float | None] = {
        "pronunciation": pronunciation,
        "grammar": judgement.grammar,
        "vocabulary": judgement.vocabulary,
        "fluency": judgement.fluency,
    }
    counts = {
        "pronunciation": ise_n,
        "grammar": 1,
        "vocabulary": 1,
        "fluency": 1,
    }
    return CompleteResponse(
        attempt_id=attempt.id,
        cefr=judgement.cefr,
        dims=dims,
        radar=[
            RadarAxisDto(dimension=dim, score=dims.get(dim), n=counts.get(dim, 0))
            for dim in DIMENSIONS
        ],
        rationale_cn=judgement.rationale_cn,
        pronunciation_source="ise" if pronunciation is not None else None,
        source="llm",
        llm_source=llm_source,
        cefr_level=cefr_level,
    )


# ====== 身份 / 归属 ======


async def _resolve_user(db: AsyncSession, identity: _Identity) -> User:
    """start 的身份口径 (course_sessions._resolve_user 同款): device 找/建, user_id 精确."""
    if not identity.device_id and not identity.user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    user = await lookup_user(
        db, device_id=identity.device_id, user_id=identity.user_id, create=True
    )
    if user is None:  # pragma: no cover —— create=True 时 device 必返回行
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    return user


async def _load_owned_attempt(
    db: AsyncSession, attempt_id: str, identity: _Identity
) -> AssessmentAttempt:
    """attempt 归属判定: 不存在 404, 不是本人的 403 (与 GET /sessions 同一套语义)."""
    attempt = (
        await db.execute(select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id))
    ).scalar_one_or_none()
    if attempt is None:
        raise AppError(404, f"assessment attempt {attempt_id} not found", "ATTEMPT_NOT_FOUND")
    if not identity.device_id and not identity.user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    user = await lookup_user(db, device_id=identity.device_id, user_id=identity.user_id)
    if user is None or attempt.user_id != user.id:
        raise AppError(
            403, "this assessment attempt belongs to another learner", "FORBIDDEN_ATTEMPT"
        )
    return attempt


async def _answers_count(db: AsyncSession, attempt_id: str) -> int:
    rows = await db.execute(
        select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id)
    )
    return len(rows.scalars().all())

"""两段式课程生成引擎 (计划 §5.5-1 + §七 P4).

「说出学习目标 → 30 秒生成专属 AI 情景课」的后端实现:

* ``POST /scenes/generate`` 只建 ``generation_jobs`` 行 + ``asyncio.create_task``
  后台跑 :func:`run_generation_job`, 立即 202 返回轮询地址;
* **全量单次生成实测 ~4 分钟, 必须拆段** (任务书硬要求): 段1 出骨架
  (标题/简介/词汇/实战设定与任务清单), 段2 补打基础步骤 + 实战剧本 —— 每段一次
  LLM 调用, ``progress`` / ``stage_text`` 随段推进落行, 客户端轮询
  ``GET /scenes/jobs/{job_id}`` 渲染三段进度;
* 每段 JSON 过 pydantic 校验, 坏输出**回喂校验错误重试 1 次** (§5.5 统一模式),
  再失败 ``job=failed`` + ``failure_reason`` (诚实报错, UI 可重试);
* prompt 硬约束 (T2 教训): 每条学员台词 ≤14 词、每条任务只含一个可听判定目标、
  b 行必须接住 a 行、词汇必须真出现在对话里;
* 成功 -> ``scene_courses`` 行 (``source="generated"``, ``status="ready"``) +
  :func:`app.services.scene_store.invalidate_cache`。

**JSON 列纪律** (T3 钉死): ``scene_courses.doc`` 读要 deepcopy、写要整体换对象。

模型恒走服务端默认 (``LLM_DEFAULT_MODEL`` -> 回退链): 生成不吃客户端 model_id。
本模块**不持有事务纪律负担**: 后台任务自开会话, 每次进度推进即 commit (轮询读的是
另一个会话), 失败时 rollback 后单独落 ``failed`` 行。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.models.course import (
    CATEGORY_ORDER,
    CEFR_LEVELS,
    SCENE_COURSE_SCHEMA_VERSION,
    MissionTask,
    SceneCourse,
    VocabItem,
)
from app.models.db import GenerationJob, SceneCourseRow
from app.services import scene_store
from app.services.drill_grader import (
    LlmUnavailableError,
    _judge,
    _truncate,
)
from app.services.llm_provider import LlmMessage

# ====== 常量 ======

#: 单段生成的超时与 token 预算 (~2000 token 的整课 JSON, 远大于判分的 20s/400).
#: 段间用 ``progress``/``stage_text`` 推进 + 前端轮询消化等待, 所以单段可以放宽.
#: 真机探针 (2026-09-05, qwen3.8-max): 骨架段单次尝试实测 ~200-240s (免费额度限速,
#: ~3 token/s), provider 层 max_retries=2 会再补射 —— 90s 会在真链路上必然超时,
#: 因此放宽到 240s/次调用 (测试 mock provider, 不受此值影响).
GEN_TIMEOUT_S = 240.0
SKELETON_MAX_TOKENS = 1600
DETAIL_MAX_TOKENS = 2200

#: goal_text 的归一化去重键长度 (scene_key 列宽 64).
_SCENE_KEY_LEN = 40

_T = TypeVar("_T", bound=BaseModel)

_JOBS: set[asyncio.Task[None]] = set()


class GenerationError(Exception):
    """生成链路失败 (LLM 不可用 / 输出两次都不合规 / 内容校验不过)."""


class SkeletonCourse(BaseModel):
    """段1 产物: 课程骨架 (标题/词汇/实战设定/任务清单; 剧本与步骤留给段2)."""

    title: str = Field(min_length=1, max_length=120)
    subtitle_en: str = Field(default="", max_length=200)
    category: str
    level: str
    est_minutes: int = Field(default=8, ge=1, le=60)
    brief_cn: str = Field(default="", max_length=2000)
    skills: list[str] = Field(min_length=1, max_length=5)
    vocab: list[VocabItem] = Field(min_length=6, max_length=12)
    persona_cn: str = Field(min_length=1, max_length=300)
    user_role_cn: str = Field(min_length=1, max_length=300)
    context_cn: str = Field(min_length=1, max_length=1000)
    opening_a: str = Field(min_length=1, max_length=500)
    opening_a_cn: str = Field(default="", max_length=500)
    tasks: list[MissionTask] = Field(min_length=3, max_length=6)
    max_turns: int = Field(default=12, ge=4, le=40)

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        # 在段1就挡住非法值 —— _judge 的重试把校验错误回喂给模型修正.
        if v not in CATEGORY_ORDER:
            raise ValueError(f"category must be one of {list(CATEGORY_ORDER)}")
        return v

    @field_validator("level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        if v not in CEFR_LEVELS:
            raise ValueError(f"level must be one of {list(CEFR_LEVELS)}")
        return v

    @field_validator("skills")
    @classmethod
    def _check_skills(cls, v: list[str]) -> list[str]:
        allowed = {"pronunciation", "grammar", "vocabulary", "fluency", "communication"}
        if len(set(v)) != len(v) or any(item not in allowed for item in v):
            raise ValueError(f"skills must be unique values from {sorted(allowed)}")
        return v


class BriefingStepDraft(BaseModel):
    """段2 的一步打基础 (题型决定哪些字段必填, 整课校验在 :class:`SceneCourse`)."""

    type: str
    cn_prompt: str = Field(min_length=1, max_length=500)
    ref_text: str = Field(default="", max_length=2000)
    translation_cn: str = Field(default="", max_length=1000)
    reference_answer: str = Field(default="", max_length=2000)
    target_word: str = Field(default="", max_length=64)
    accept_notes: str = Field(default="", max_length=500)


class ExchangeDraft(BaseModel):
    """段2 的一对往来得台词 (a=AI, b=学员)."""

    a: str = Field(min_length=1, max_length=500)
    b: str = Field(min_length=1, max_length=500)
    a_cn: str = Field(default="", max_length=500)
    b_cn: str = Field(default="", max_length=500)


class CourseDetail(BaseModel):
    """段2 产物: 打基础步骤 + 实战剧本."""

    briefing: list[BriefingStepDraft] = Field(min_length=4, max_length=7)
    exchanges: list[ExchangeDraft] = Field(min_length=2, max_length=16)


# ====== prompts (§5.5-1; T2 起草脚本里实测首轮通过的那套约束) ======


def _skeleton_messages(goal_text: str, category: str, level: str) -> list[LlmMessage]:
    constraints = (
        f"学习目标: {goal_text}\n"
        + (
            f"分类锁定: {category}。"
            if category
            else "分类按目标自选 daily|workplace|exam|travel。\n"
        )
        + (f"难度锁定: {level}。" if level else "难度按目标自选 A1..C2。\n")
    )
    system = (
        "你是英语情景课的备课主编, 学员是中文母语的企业管理者: 读写强、开口少。"
        "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。\n"
        "本次生成「课程骨架」: 标题/简介/核心词汇/实战设定与任务清单; "
        "打基础步骤和对话剧本由下一步补齐, 你不用输出。\n"
        "硬约束 (违反任何一条都算不合格):\n"
        "- category ∈ daily|workplace|exam|travel; level ∈ A1|A2|B1|B2|C1|C2\n"
        "- skills 从 pronunciation|grammar|vocabulary|fluency|communication 里选 1-5 个, 不重复\n"
        "- vocab 6-12 个: word/ipa(带斜杠)/meaning_cn/example_en, example_en 必须包含该 word, word 互不重复\n"
        "- 每条任务只包含**一个**可听判定目标 (一句话能说清、说完即算达成); "
        "desc_cn 用中文, hint_en 是能直接开口的英文示范短句, hint_cn 一句中文提示\n"
        "- tasks 3-6 条, 至少 3 条 required=true, 任务合起来正好是「完成这次沟通」\n"
        "- opening_a 是 AI 角色的英文开场白 (≤20 词), 要自然引出第一个任务; "
        "opening_a_cn 是它的中文对照\n"
        "- max_turns 覆盖全部必做任务还留有余量 (4-40)\n"
        '只输出 JSON: {"title", "subtitle_en", "category", "level", "est_minutes", '
        '"brief_cn", "skills", "vocab", "persona_cn", "user_role_cn", "context_cn", '
        '"opening_a", "opening_a_cn", "tasks", "max_turns"}'
    )
    return [LlmMessage(role="system", content=system), LlmMessage(role="user", content=constraints)]


def _detail_messages(skeleton: SkeletonCourse) -> list[LlmMessage]:
    vocab_words = ", ".join(item.word for item in skeleton.vocab)
    tasks_block = "\n".join(
        f"- {task.id or f't{i}'}: {task.desc_cn} (示范: {task.hint_en})"
        for i, task in enumerate(skeleton.tasks, start=1)
    )
    system = (
        "你是英语情景课的备课主编, 学员是中文母语的企业管理者: 读写强、开口少。"
        "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。\n"
        "课程骨架已定 (标题/词汇/任务清单), 本次只补两块: 打基础步骤 + 实战对话剧本。\n"
        "硬约束 (违反任何一条都算不合格):\n"
        "- briefing 4-7 步, 尽量覆盖全部四种题型 read_along|retell|translate|make_sentence: "
        "read_along 的 ref_text 是英文原句 (translation_cn 中文对照); "
        "retell 的 ref_text 是 2-3 句英文材料、reference_answer 是参考要点; "
        "translate 的 ref_text 是**中文原句**、reference_answer 是参考英文译文; "
        "make_sentence 给 target_word + reference_answer; "
        "每步都要 cn_prompt (中文题干) 和 accept_notes (中文评分要点)\n"
        '- exchanges 5-12 对, 每对 {"a","b","a_cn","b_cn"}: a 是 AI 角色台词, '
        "b 是学员台词, 中文对照齐全\n"
        "- **每条学员台词 (b 行) 最多 14 个英文单词**\n"
        "- b 行必须接住 a 行: 直接回应对方的话, 不答非所问; 对话按场景自然推进并收尾\n"
        "- 每个必做任务都能在剧本里找到学员对应的那句 b (任务判定以听得见为准)\n"
        f"- 词汇 ({vocab_words}) 必须真出现在 exchanges 的 a 或 b 行里\n"
        f"- 全部英文锚定 {skeleton.level}, 口语化短句\n"
        '只输出 JSON: {"briefing":[...], "exchanges":[...]}'
    )
    user = (
        f"课程: {skeleton.title} ({skeleton.category}/{skeleton.level})\n"
        f"实战设定: 学员演 {skeleton.user_role_cn}, AI 演 {skeleton.persona_cn}。"
        f"{skeleton.context_cn}\n"
        f"开场白: {skeleton.opening_a}\n"
        f"任务清单:\n{tasks_block}"
    )
    return [LlmMessage(role="system", content=system), LlmMessage(role="user", content=user)]


# ====== LLM 两段调用 ======


async def _ask(schema: type[_T], messages: list[LlmMessage], *, max_tokens: int) -> _T:
    """一段生成: 1 次调用 + 容错解析, 坏输出回喂重试 1 次, 再坏 -> :class:`GenerationError`."""
    try:
        return await _judge(
            schema, messages, max_tokens=max_tokens, timeout=GEN_TIMEOUT_S, temperature=0.4
        )
    except LlmUnavailableError as exc:
        raise GenerationError(str(exc)) from exc


# ====== job runner ======


def scene_key_for(goal_text: str) -> str:
    """goal_text -> 去重键 (同一用户同一目标复用同一行, upsert 不堆课)."""
    normalized = re.sub(r"\s+", " ", goal_text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:_SCENE_KEY_LEN]


def _new_course_id() -> str:
    return f"scene_g{uuid.uuid4().hex[:12]}"


async def _load_job(db: AsyncSession, job_id: str) -> GenerationJob | None:
    res = await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    return res.scalar_one_or_none()


async def _bump(db: AsyncSession, job: GenerationJob, progress: float, stage_text: str) -> None:
    """段间推进: 立即 commit —— 轮询端点在另一个会话里读, 不落库客户端就看不见."""
    job.progress = progress
    job.stage_text = stage_text
    job.updated_at = _utcnow()
    await db.commit()


async def _fail(db: AsyncSession, job_id: str, reason: str) -> None:
    """rollback 后单独落 ``failed`` 行 (失败原因诚实给到客户端)."""
    await db.rollback()
    job = await _load_job(db, job_id)
    if job is None or job.status != "running":
        return
    job.status = "failed"
    job.error = _truncate(reason, 500)
    job.stage_text = "生成失败, 可重试"
    job.updated_at = _utcnow()
    await db.commit()
    logger.warning("course generation failed | job={} reason={}", job_id, _truncate(reason, 200))


async def run_generation_job(job_id: str) -> None:
    """后台任务主体: 自开会话, 两段生成, 逐段推进 job 行.

    ``spawn_job`` 的测试替身直接 ``await`` 本函数; 任何异常都收敛成 ``job=failed``,
    绝不让后台任务无声死去 (轮询端永远等得到一个终态)。
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        job = await _load_job(db, job_id)
        if job is None or job.status != "running":
            return
        try:
            await _run_job(db, job)
        except Exception as exc:
            logger.exception("course generation crashed | job={}", job_id)
            await _fail(db, job_id, f"生成失败: {exc}")


async def _run_job(db: AsyncSession, job: GenerationJob) -> None:
    await _bump(db, job, 0.05, "理解学习目标…")
    skeleton = await _ask(
        SkeletonCourse,
        _skeleton_messages(job.goal_text, job.category, job.level),
        max_tokens=SKELETON_MAX_TOKENS,
    )
    await _bump(db, job, 0.5, "设计任务与对话…")
    detail = await _ask(CourseDetail, _detail_messages(skeleton), max_tokens=DETAIL_MAX_TOKENS)
    await _bump(db, job, 0.9, "校验内容并保存…")
    course = _assemble_course(job, skeleton, detail)
    scene_id = await _persist_course(db, job, course)
    job.status = "ready"
    job.progress = 1.0
    job.stage_text = "生成完成"
    job.scene_id = scene_id
    job.updated_at = _utcnow()
    await db.commit()
    scene_store.invalidate_cache()
    logger.info(
        "course generated | job={} scene={} title={} steps={} exchanges={}",
        job.id,
        scene_id,
        course.title,
        len(course.briefing),
        len(course.mission.exchanges),
    )


def _assemble_course(
    job: GenerationJob, skeleton: SkeletonCourse, detail: CourseDetail
) -> SceneCourse:
    """两段产物 -> 完整 :class:`SceneCourse` (pydantic 整体把关 = 内容质量的最后防线)."""
    briefing: list[dict[str, Any]] = []
    for index, step in enumerate(detail.briefing, start=1):
        briefing.append({"id": f"f{index}", **step.model_dump(exclude_none=True)})
    tasks: list[dict[str, Any]] = []
    for index, task in enumerate(skeleton.tasks, start=1):
        dump = task.model_dump(exclude_none=True)
        dump["id"] = f"t{index}"  # 任务 id 统一重编号 (curated 同款 t1..tN), 不信 LLM 的命名
        tasks.append(dump)
    payload: dict[str, Any] = {
        "schema_version": SCENE_COURSE_SCHEMA_VERSION,
        "id": _new_course_id(),
        "source": "generated",
        "category": skeleton.category,
        "title": skeleton.title,
        "subtitle_en": skeleton.subtitle_en,
        "goal_text": job.goal_text,
        "level": skeleton.level,
        "est_minutes": skeleton.est_minutes,
        "brief_cn": skeleton.brief_cn,
        "vocab": [item.model_dump(exclude_none=True) for item in skeleton.vocab],
        "briefing": briefing,
        "mission": {
            "persona_cn": skeleton.persona_cn,
            "user_role_cn": skeleton.user_role_cn,
            "context_cn": skeleton.context_cn,
            "opening_a": skeleton.opening_a,
            "opening_a_cn": skeleton.opening_a_cn,
            "exchanges": [ex.model_dump(exclude_none=True) for ex in detail.exchanges],
            "tasks": tasks,
            "max_turns": skeleton.max_turns,
        },
        "skills": skeleton.skills,
    }
    try:
        return SceneCourse.model_validate(payload)
    except ValidationError as exc:
        # 两段各自合法但拼不成整课 (最常见: 题型缺料) —— 诚实报错, 不静默降级.
        raise GenerationError(f"整课内容校验未通过: {_truncate(str(exc), 300)}") from exc


async def _persist_course(db: AsyncSession, job: GenerationJob, course: SceneCourse) -> str:
    """写 ``scene_courses``: 同 (user, scene_key) 复用旧行与旧 id (重新生成 = 覆盖)."""
    doc = course.model_dump(mode="json")
    row = (
        await db.execute(
            select(SceneCourseRow).where(
                SceneCourseRow.user_id == job.user_id,
                SceneCourseRow.scene_key == scene_key_for(job.goal_text),
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        old_id = ""
        if isinstance(row.doc, dict) and isinstance(row.doc.get("id"), str):
            old_id = str(row.doc["id"])
        doc["id"] = old_id or doc["id"]
        course = SceneCourse.model_validate(doc)
        doc = course.model_dump(mode="json")
        # JSON 列整体换对象 (原地改不会被 UPDATE, T3 钉死的坑).
        row.doc = doc
        row.status = "ready"
        row.updated_at = _utcnow()
    else:
        db.add(
            SceneCourseRow(
                user_id=job.user_id,
                scene_key=scene_key_for(job.goal_text),
                doc=doc,
                status="ready",
            )
        )
    try:
        await db.flush()
    except IntegrityError as exc:
        raise GenerationError("同一目标已在生成中 (并发去重)") from exc
    return str(doc["id"])


def spawn_job(job_id: str) -> None:
    """``asyncio.create_task`` 后台跑; 模块级集合防任务被 GC.

    测试 monkeypatch 本函数后直接 ``await run_generation_job(job_id)``。
    """
    task = asyncio.create_task(run_generation_job(job_id))
    _JOBS.add(task)
    task.add_done_callback(_JOBS.discard)


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "GEN_TIMEOUT_S",
    "CourseDetail",
    "GenerationError",
    "SkeletonCourse",
    "run_generation_job",
    "scene_key_for",
    "spawn_job",
]

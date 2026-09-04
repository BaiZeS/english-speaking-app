"""情景课画廊 / 详情 / 剧本 / 生成任务端点 (计划 §5.3 「目录与画廊」+ §七 P4).

P1 的只读三件套 + P4 的生成链路与进度:

=========================================  =================================================
``GET    /scenes?category=&device_id=``    分类计数 + 摘要 (生成课合并, 进度三字段变真)
``POST   /scenes/generate``                建生成任务 -> 202 {job_id, polling_url}
``GET    /scenes/jobs/{job_id}``           轮询生成进度 (progress/stage_text/终态)
``GET    /courses/progress?device_id=``    通关进度列表 (course_progress 物化直读)
``GET    /scenes/{scene_id}``              课程全量 (生成课 DB 读, 仅归属者可见)
``GET    /scenes/{scene_id}/script``       LessonDetail 形状剧本 (老 PlayerScreen 直播)
``DELETE /scenes/{scene_id}``              删自己的生成课 (curated 只读 -> 405)
=========================================  =================================================

合并纪律 (§5.3): ``scene_store.merge_courses(curated, generated)`` —— **id 冲突 DB
优先**; 画廊里 ``cleared`` / ``best_total`` / ``attempts`` 三字段从 ``course_progress``
物化读出 (T2 预告的「协议零改动, 值变真」)。生成课的可见性 = 归属该 device: 别人的
生成课一律 404 (不泄露存在性), 轮询别人的 job 是 403。
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.course import CATEGORY_ORDER, CEFR_LEVELS, Category, SceneCourse
from app.models.db import GenerationJob, SceneCourseRow, User
from app.services import course_generator, course_progress, scene_store
from app.services.scene_store import CourseProgress, SceneScript, ScenesPage
from app.services.users import lookup_user

router = APIRouter(tags=["scenes"])


def _require_category(category: str | None) -> Category | None:
    """未传 = 全部; 传了非法值 = 400 —— 不让拼错的筛选条件静默返回空列表."""
    if category is None:
        return None
    if category not in CATEGORY_ORDER:
        raise AppError(400, f"unknown category: {category}", "INVALID_CATEGORY")
    return category


async def _load_generated_courses(db: AsyncSession, user_id: str) -> list[SceneCourse]:
    """该用户的 ``ready`` 生成课 -> :class:`SceneCourse` (坏 doc 跳过, 同 T2 策略)."""
    rows = (
        (
            await db.execute(
                select(SceneCourseRow).where(
                    SceneCourseRow.user_id == user_id, SceneCourseRow.status == "ready"
                )
            )
        )
        .scalars()
        .all()
    )
    courses: list[SceneCourse] = []
    for row in rows:
        raw: Any = row.doc
        if not isinstance(raw, dict):
            logger.warning("generated scene doc skipped (not a dict) | row={}", row.id)
            continue
        try:
            # JSON 列读纪律: deepcopy 一份再校验 (不信任列里的旧数据).
            courses.append(SceneCourse.model_validate(copy.deepcopy(raw)))
        except Exception as exc:
            logger.warning("generated scene doc skipped | row={} err={}", row.id, exc)
    return courses


async def _find_generated_row(
    db: AsyncSession, user_id: str, scene_id: str
) -> SceneCourseRow | None:
    """按课程 id (doc["id"]) 找本用户的生成课行; 无归属/未就绪都算没有."""
    rows = (
        (
            await db.execute(
                select(SceneCourseRow).where(
                    SceneCourseRow.user_id == user_id, SceneCourseRow.status == "ready"
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        raw: Any = row.doc
        if isinstance(raw, dict) and raw.get("id") == scene_id:
            return row
    return None


# ====== 画廊 ======


@router.get("/scenes", response_model=ScenesPage)
async def list_scenes(
    category: str | None = Query(default=None, min_length=1, max_length=32),
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> ScenesPage:
    """按分类返回情景课摘要.

    ``categories`` 的计数恒为全量 (四个分类都出现, 0 篇也列出); ``scenes`` 受
    ``category`` 过滤; ``total`` 是过滤后的篇数。带 ``device_id`` 时: 该用户的
    生成课与 curated 按 ``merge_courses`` 合并 (id 冲突 DB 优先), 摘要里的
    ``cleared`` / ``best_total`` / ``attempts`` 从 ``course_progress`` 物化读出
    (没玩过恒为默认值, 字段从 P1 起就稳定)。
    """
    courses = scene_store.load_curated_courses()
    progress_map: dict[str, CourseProgress] = {}
    if device_id:
        user = await lookup_user(db, device_id=device_id)
        if user is not None:
            courses = scene_store.merge_courses(courses, await _load_generated_courses(db, user.id))
            progress_map = await course_progress.load_progress_map(db, user.id)
    return scene_store.list_scenes(
        category=_require_category(category),
        device_id=device_id,
        progress=progress_map,
        courses=courses,
    )


# ====== 生成任务 (P4) ======


class GenerateRequest(BaseModel):
    """``POST /scenes/generate`` 的入参 (§5.3): 一句话说清学习目标."""

    device_id: str = Field(min_length=1, max_length=128)
    goal_text: str = Field(min_length=4, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=16)
    level: str | None = Field(default=None, min_length=1, max_length=8)


class GenerateAccepted(BaseModel):
    """202 载荷: 轮询地址直接给全 (客户端不用拼)."""

    job_id: str
    polling_url: str


class JobView(BaseModel):
    """``GET /scenes/jobs/{job_id}`` 的载荷 (生成中页面按 progress/stage_text 渲染)."""

    job_id: str
    status: str
    progress: float
    stage_text: str
    scene_id: str | None = None
    error: str | None = None


@router.post("/scenes/generate", status_code=202, response_model=GenerateAccepted)
async def generate_scene(
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> GenerateAccepted:
    """说一句学习目标 -> 后台两段生成 (§5.5-1), 立即 202 返回轮询地址.

    约束校验在入口挡下 (非法 category/level 400), 生成质量交给后台任务的
    pydantic 校验 + 回喂重试; job 终态只有 ``ready`` / ``failed`` 两种。
    """
    if req.category and req.category not in CATEGORY_ORDER:
        raise AppError(400, f"unknown category: {req.category}", "INVALID_CATEGORY")
    if req.level and req.level not in CEFR_LEVELS:
        raise AppError(400, f"unknown level: {req.level}", "INVALID_LEVEL")
    # 写侧口径: device 未注册就建行 (与 POST /sessions / POST /history 一致).
    user = await lookup_user(db, device_id=req.device_id, create=True)
    if user is None:  # pragma: no cover —— create=True 的 device 路径必返回行
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    job = GenerationJob(
        user_id=user.id,
        goal_text=req.goal_text.strip(),
        category=req.category or "",
        level=req.level or "",
        status="running",
        progress=0.0,
        stage_text="排队中…",
    )
    db.add(job)
    await db.commit()
    course_generator.spawn_job(job.id)
    logger.info(
        "generation job queued | job={} user={} goal_len={}", job.id, user.id, len(req.goal_text)
    )
    return GenerateAccepted(job_id=job.id, polling_url=f"/api/v1/scenes/jobs/{job.id}")


async def _identity_user(
    db: AsyncSession,
    device_id: str | None,
    user_id: str | None,
) -> User | None:
    """GET 侧身份定位: 只查不注册; 两个都没给 -> 400 (与 course_sessions 一致)."""
    if not device_id and not user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    return await lookup_user(db, device_id=device_id, user_id=user_id)


@router.get("/scenes/jobs/{job_id}", response_model=JobView)
async def get_generation_job(
    job_id: str,
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> JobView:
    """轮询生成进度; 终态 ``ready`` 带 ``scene_id``, ``failed`` 带 ``error``."""
    user = await _identity_user(db, device_id, user_id)
    job = (
        await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise AppError(404, f"generation job {job_id} not found", "JOB_NOT_FOUND")
    if user is None or job.user_id != user.id:
        raise AppError(403, "this generation job belongs to another learner", "FORBIDDEN_JOB")
    return JobView(
        job_id=job.id,
        status=job.status,
        progress=float(job.progress),
        stage_text=job.stage_text,
        scene_id=job.scene_id or None,
        error=job.error,
    )


class ProgressItem(BaseModel):
    """``GET /courses/progress`` 的一行 (一门课的通关现状)."""

    scene_id: str
    attempts: int
    cleared: bool
    best_total: float
    last_stage: str
    last_session_id: str
    estimated_seconds: float


class ProgressPage(BaseModel):
    total: int
    progress: list[ProgressItem]


@router.get("/courses/progress", response_model=ProgressPage)
async def list_course_progress(
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> ProgressPage:
    """通关进度列表 (首页「继续学习」/ 课程卡徽章直读, 不做 GROUP BY)."""
    user = await _identity_user(db, device_id, user_id)
    if user is None:
        return ProgressPage(total=0, progress=[])
    rows = await course_progress.list_rows(db, user.id)
    items = [
        ProgressItem(
            scene_id=row.scene_id,
            attempts=int(row.attempts),
            cleared=bool(row.cleared),
            best_total=float(row.best_total),
            last_stage=row.last_stage,
            last_session_id=row.last_session_id,
            estimated_seconds=float(row.estimated_seconds),
        )
        for row in rows
    ]
    return ProgressPage(total=len(items), progress=items)


# ====== 详情 / 剧本 / 删除 ======


async def _owned_generated_course(
    db: AsyncSession, device_id: str | None, user_id: str | None, scene_id: str
) -> SceneCourse | None:
    """带身份时先看生成课 (仅归属者可见); 没身份/不是本人 -> None 走 curated 回落."""
    if not device_id and not user_id:
        return None
    user = await lookup_user(db, device_id=device_id, user_id=user_id)
    if user is None:
        return None
    row = await _find_generated_row(db, user.id, scene_id)
    if row is None or not isinstance(row.doc, dict):
        return None
    try:
        return SceneCourse.model_validate(copy.deepcopy(row.doc))
    except Exception as exc:
        logger.warning("generated scene doc unreadable | scene={} err={}", scene_id, exc)
        return None


async def _load_scene(
    db: AsyncSession, scene_id: str, device_id: str | None, user_id: str | None
) -> SceneCourse:
    """详情读路径: 生成课 (DB, 仅归属者) 优先, curated 回落; 都没有 -> 404."""
    course = await _owned_generated_course(db, device_id, user_id, scene_id)
    if course is None:
        course = scene_store.get_course(scene_id)  # 非法 id 在这里抛 400
    if course is None:
        raise AppError(404, f"scene {scene_id} not found", "SCENE_NOT_FOUND")
    return course


@router.get("/scenes/{scene_id}", response_model=SceneCourse)
async def get_scene(
    scene_id: str,
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> SceneCourse:
    """一门课的完整内容: 词汇卡 + 打基础步骤 + 实战剧本与通关任务清单.

    生成课经 DB 读且**仅归属该 device 可见** (别人的 -> 404); 不带身份的老客户端
    照旧只能看到 curated。
    """
    return await _load_scene(db, scene_id, device_id, user_id)


@router.get("/scenes/{scene_id}/script", response_model=SceneScript)
async def get_scene_script(
    scene_id: str,
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> SceneScript:
    """实战对话参考剧本, 形状等同 ``GET /lessons/{lesson_id}/roles`` 的 LessonDetail.

    role A = AI 台词, role B = 学员台词 (学员恒演 B), 两角色句数由 exchange 成对
    结构保证相等 —— 生成课的剧本同样从 doc 里的 exchanges 投影, 老 PlayerScreen
    零改动可播。
    """
    course = await _load_scene(db, scene_id, device_id, user_id)
    return scene_store.to_script(course)


@router.delete("/scenes/{scene_id}", status_code=204)
async def delete_scene(
    scene_id: str,
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """删除**自己的生成课**; curated 是仓库内容, 一律 405 不许删.

    删完顺手清 curated TTL 缓存是无害的 (缓存里本来就没有 DB 课), 但生成课要从
    下一次合并里消失, 归属判定先行: 没身份 400, 不是本人的行 404 (不泄露存在性)。
    """
    if not device_id and not user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    if scene_store.get_course(scene_id) is not None:
        raise AppError(405, "curated scenes are read-only", "CURATED_SCENE_READONLY")
    user = await lookup_user(db, device_id=device_id, user_id=user_id)
    if user is None:
        raise AppError(404, f"scene {scene_id} not found", "SCENE_NOT_FOUND")
    row = await _find_generated_row(db, user.id, scene_id)
    if row is None:
        raise AppError(404, f"scene {scene_id} not found", "SCENE_NOT_FOUND")
    await db.delete(row)
    await db.commit()
    scene_store.invalidate_cache()
    logger.info("generated scene deleted | scene={} user={}", scene_id, user.id)
    return Response(status_code=204)

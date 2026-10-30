"""``GET /scenes/jobs/{job_id}`` —— 后台生成任务的轮询路由.

v3.0 大扫除之后本模块**只剩这一条**: 整课画廊/详情/剧本/生成/进度那批端点随"单词 +
课程"产品线一起退役了。它必须留着, 因为自定义对话场景的骨架作业 (``POST
/dialogue/scenes/custom`` → 202) 与当年的整课生成**共用同一张 ``generation_jobs``
表和同一条轮询地址** —— 客户端只认 ``polling_url``, 而那个 URL 就指到这里。

归属纪律不变: 别人的 job 是 403, 未知 job 是 404 (不泄露存在性的只有 404 那一半)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import GenerationJob, User
from app.services.users import lookup_user

router = APIRouter(tags=["scenes"])


class JobView(BaseModel):
    """``GET /scenes/jobs/{job_id}`` 的载荷 (生成中页面按 progress/stage_text 渲染)."""

    job_id: str
    status: str
    progress: float
    stage_text: str
    scene_id: str | None = None
    error: str | None = None
    #: 两种后台任务同居 ``generation_jobs``, 这一列让客户端分得开 ``course`` (整课,
    #: 已退役但存量行还在) 与 ``scene_brief`` (自定义对话场景)。
    kind: str = "course"


async def _identity_user(
    db: AsyncSession,
    device_id: str | None,
    user_id: str | None,
) -> User | None:
    """GET 侧身份定位: 只查不注册; 两个都没给 -> 400."""
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
        kind=job.kind or "course",
    )

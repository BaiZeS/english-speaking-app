"""自定义场景端点 (计划 §3 C3) —— 学员自己描场景 -> ``scene_brief`` 后台作业.

===============================  =================================================
``POST /dialogue/scenes/custom``  建场景骨架任务 -> 202 {job_id, polling_url}
===============================  =================================================

LLM **不进这条请求** (§3 C3 "不加同步 LLM 路径"): 同步校验只有身份与长度, 然后写一行
``generation_jobs`` (``kind="scene_brief"``, 与整课生成同居一张表、同一个轮询端点,
靠 kind 区分) + 派生后台任务, 立即 202 回轮询地址。作业形状与场景行 upsert 在
:mod:`app.services.scene_spec_generator`; 读侧合并 (``GET /dialogue/scenes`` 带身份
时并自定义场景) 在 ``api/v1/dialogue.py``。

身份口径 (B4 裁决: 安卓场景选择器会带 ``device_id``/``user_id``, 安卓侧 T5 接通,
这条先接服务端身份线): 写侧照 ``POST /scenes/generate`` —— device 未注册就建行,
两个都没给 400, 认不出的 ``user_id`` 404 (不泄露, 但也不凭空给归属)。
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import GenerationJob, User
from app.services import scene_spec_generator, users

router = APIRouter(tags=["dialogue"])


class CustomSceneRequest(BaseModel):
    """``POST /dialogue/scenes/custom`` 的入参: 学员自己写的一段场景描述."""

    #: 一句话到一小段话都行 (长度门同 goal_text 的 4..200: 再长 prompt 也吃不消).
    scene_brief: str = Field(min_length=4, max_length=200)
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=36)
    #: **没有** ``model_id``: 这是生成类 (D2 允许跟随客户端模型), 但 job 表没有承载
    #: 模型 id 的列, 后台任务拿不到"当时选的那个" —— 与其默默吃掉这个参数, 不开这个口
    #: (整课生成 ``POST /scenes/generate`` 同理恒走服务端默认)。


class CustomSceneAccepted(BaseModel):
    """202 载荷: 照 ``scenes.GenerateAccepted`` —— 轮询地址直接给全, 客户端不用拼."""

    job_id: str
    polling_url: str


async def _require_identity(db: AsyncSession, device_id: str | None, user_id: str | None) -> User:
    """写侧身份: device 找/建, 未知 user_id 404; 两个都没给 400.

    ``create=True`` 自己保证有值: 未知 ``user_id`` 在 :func:`users.lookup_user` 内部当场
    404 (不返回 ``None``), ``device_id`` 走 get-or-create 必返回行 —— 所以这里没有"返回
    ``None``"的分支可兜 (``cast`` 只是把那份保证写给 mypy).
    """
    if user_id:
        return cast("User", await users.lookup_user(db, user_id=user_id, create=True))
    if not device_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    return cast("User", await users.lookup_user(db, device_id=device_id, create=True))


@router.post("/dialogue/scenes/custom", status_code=202, response_model=CustomSceneAccepted)
async def create_custom_scene(
    req: CustomSceneRequest,
    db: AsyncSession = Depends(get_db),
) -> CustomSceneAccepted:
    """描一个场景 -> 后台出骨架 (§3 C2/C3), 立即 202 返回轮询地址.

    ``GET /scenes/jobs/{job_id}`` 轮进度 (``kind="scene_brief"``), 终态 ``ready`` 带
    ``scene_id = custom_<行 id>``; 就绪后 ``GET /dialogue/scenes`` (带同一身份) 里就
    会出现它。job 终态只有 ``ready``/``failed`` 两种 —— 轮询永远等得到答案。
    """
    user = await _require_identity(db, req.device_id, req.user_id)
    job = GenerationJob(
        user_id=user.id,
        kind="scene_brief",
        goal_text=req.scene_brief.strip(),
        status="running",
        progress=0.0,
        stage_text="排队中…",
    )
    db.add(job)
    await db.commit()
    scene_spec_generator.spawn_scene_brief_job(job.id)
    logger.info(
        "scene brief job queued | job={} user={} brief_len={}",
        job.id,
        user.id,
        len(req.scene_brief),
    )
    return CustomSceneAccepted(job_id=job.id, polling_url=f"/api/v1/scenes/jobs/{job.id}")

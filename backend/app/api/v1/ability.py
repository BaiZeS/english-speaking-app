"""能力画像端点 (计划 §5.6 / §5.3 ``GET /ability``; 阶段 P3).

``GET /api/v1/ability?device_id=dev-1&days=30`` 一次给齐画像页要的所有东西:

* ``profile`` / ``n`` / ``radar`` —— 画像快照 (4 维 EWMA 分 + 每维样本数;
  维度 ``null`` = 没有被计入的可信证据, **别渲染成 0 分**);
* ``cefr_level`` —— 权威 CEFR (**测评前恒 ``null``**, "未测评就是未测评");
  ``assessment_cefr`` / ``band_locked`` 是 §5.2 的锁带字段, 测评 (P4) 写前者;
  ``derived_level`` 只是从四维分映射的中性辅助提示, 不冒充官方等级;
* ``trajectory`` —— 从 ``ability_events`` 全量流水聚合的逐日均值序列 (只聚合
  ``weight>0`` 的证据: 本机没讯飞 key 时画像与轨迹都不会被 stub 拉动, 这正是
  §四 决策表要的"画像不被污染").

轨迹窗口只接受 7/30/90 天 (计划 §5.3); 未知 device 返回空画像视图 (全 null),
不报 404 —— 画像页在用户第一次登录前也要能渲染骨架。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import AbilityEvent, User
from app.services import ability_engine
from app.services.ability_engine import DIMENSIONS

router = APIRouter(tags=["ability"])

#: 轨迹窗口 (§5.3: days=7|30|90).
ALLOWED_DAYS: tuple[int, ...] = (7, 30, 90)

#: 单用户流水的读取上限 (轨迹/画像重建的护栏; 按时间倒序取最近 N 条).
_EVENT_SCAN_LIMIT = 5000


class RadarAxis(BaseModel):
    """雷达图的一轴 (score=None 表示该维度没有可信证据)."""

    dimension: str
    score: float | None
    max: float = 100.0
    n: int = 0


class TrajectoryPointDto(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    pronunciation: float | None
    grammar: float | None
    vocabulary: float | None
    fluency: float | None
    events: int = Field(description="当天计入轨迹的证据条数")


class AbilityResponse(BaseModel):
    device_id: str
    user_id: str | None = None
    user_found: bool
    #: 4 维 EWMA 快照 (null = 无证据).
    profile: dict[str, float | None]
    #: 每维**被计入画像**的样本数 (stub 门控事件不计数, 但保留在流水里).
    n: dict[str, int]
    radar: list[RadarAxis] = Field(default_factory=list)
    #: 权威 CEFR: **测评 (P4) 之前为 null**.
    cefr_level: str | None = None
    assessment_cefr: str | None = None
    band_locked: bool = False
    #: 四维分映射出的辅助等级 (不是官方结论).
    derived_level: str | None = None
    days: int
    trajectory: list[TrajectoryPointDto] = Field(default_factory=list)
    real_events: int = Field(default=0, description="窗口内未门控的证据条数")
    updated_at: str | None = None


@router.get("/ability", response_model=AbilityResponse)
async def get_ability(
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    days: int = Query(default=30),
    db: AsyncSession = Depends(get_db),
) -> AbilityResponse:
    """画像快照 + 四维雷达 + 轨迹序列 (§5.6 的读侧).

    ``days`` 只接受 7/30/90 (§5.3); 其它值 400 ``ABILITY_DAYS_INVALID``。
    """
    if days not in ALLOWED_DAYS:
        raise AppError(400, f"days must be one of {list(ALLOWED_DAYS)}", "ABILITY_DAYS_INVALID")
    if not device_id and not user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")
    if user_id:
        res = await db.execute(select(User).where(User.id == user_id))
    else:
        res = await db.execute(select(User).where(User.device_id == str(device_id)))
    user = res.scalar_one_or_none()
    if user is None:
        # 没练过的设备: 空画像骨架 (全 null / n=0 / 轨迹空) —— 不是错误.
        return AbilityResponse(
            device_id=str(device_id or ""),
            user_id=None,
            user_found=False,
            profile=dict.fromkeys(DIMENSIONS),
            n=dict.fromkeys(DIMENSIONS, 0),
            radar=[RadarAxis(dimension=dim, score=None, n=0) for dim in DIMENSIONS],
            days=days,
        )
    snapshot = await ability_engine.get_snapshot(db, user.id)
    rows = (
        await db.execute(
            select(
                AbilityEvent.created_at,
                AbilityEvent.dimension,
                AbilityEvent.score,
                AbilityEvent.weight,
            )
            .where(AbilityEvent.user_id == user.id)
            .order_by(AbilityEvent.created_at.desc())
            .limit(_EVENT_SCAN_LIMIT)
        )
    ).all()
    chronological: list[tuple[datetime, str, float, float]] = [
        (created_at, dimension, score, weight)
        for created_at, dimension, score, weight in reversed(list(rows))
    ]
    points = ability_engine.bucket_events(chronological, days=days)
    return AbilityResponse(
        device_id=str(device_id or user.device_id),
        user_id=user.id,
        user_found=True,
        profile=snapshot.dims,
        n=snapshot.counts,
        radar=[
            RadarAxis(dimension=dim, score=snapshot.dims.get(dim), n=snapshot.counts.get(dim, 0))
            for dim in DIMENSIONS
        ],
        cefr_level=ability_engine.resolve_level(
            assessment=snapshot.assessment_cefr,
            derived=ability_engine.derived_level(snapshot.dims),
            band_locked=snapshot.band_locked,
        ),
        assessment_cefr=snapshot.assessment_cefr,
        band_locked=snapshot.band_locked,
        derived_level=ability_engine.derived_level(snapshot.dims),
        days=days,
        trajectory=[
            TrajectoryPointDto(
                date=point.date,
                pronunciation=point.pronunciation,
                grammar=point.grammar,
                vocabulary=point.vocabulary,
                fluency=point.fluency,
                events=point.events,
            )
            for point in points
        ],
        real_events=sum(1 for *_r, weight in chronological if weight > 0),
        updated_at=snapshot.updated_at,
    )

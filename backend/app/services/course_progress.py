"""``course_progress`` 物化的写侧 (计划 §5.2 M3「不做 GROUP BY 的物化视图」).

每次 mission 收工 (``_finish_mission_state``) 落一行 upsert —— 用方言原生的
``INSERT .. ON CONFLICT DO UPDATE`` (PG16 与 sqlite 双通) **一条语句**完成:

* ``attempts``       自增 (一场收工 = 一次尝试);
* ``best_total``     **单调** GREATEST (旧值与新值取大; 用 CASE 表达, 两个方言都渲染);
* ``cleared``        取或 (通关过一次就永远是通关过的课);
* ``last_stage`` / ``last_session_id`` 覆盖为最新一场;
* ``estimated_seconds`` 累加 (实战开始 -> 收工的秒数).

语句级原子性 + 唯一复合主键让并发收工不丢更新 (best_total 单调由 CASE 保证,
先后顺序只影响 last_* 记谁)。**不 commit** —— 与调用方的 doc/history 行同事务,
输掉乐观锁时一起回滚。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import CourseProgressRow
from app.services.scene_store import CourseProgress


def _dialect_insert(db: AsyncSession) -> Any:
    """按绑定的方言选 ``INSERT .. ON CONFLICT`` 构造器 (本仓库只有 sqlite/PG16)."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert(CourseProgressRow)
    return sqlite_insert(CourseProgressRow)


async def record_finished_session(
    db: AsyncSession,
    *,
    user_id: str,
    scene_id: str,
    session_id: str,
    cleared: bool,
    best_total: float | None,
    last_stage: str,
    session_seconds: float,
) -> None:
    """一次收工 upsert 一行进度 (见模块 docstring 的合并规则).

    ``best_total=None`` (没有可信分数) 按 0 参与 GREATEST —— 不会把已有最高分拉低。
    """
    new_best = max(0.0, float(best_total or 0.0))
    new_seconds = max(0.0, float(session_seconds))
    insert_stmt = _dialect_insert(db).values(
        user_id=user_id,
        scene_id=scene_id,
        attempts=1,
        cleared=bool(cleared),
        best_total=new_best,
        last_stage=str(last_stage or ""),
        last_session_id=str(session_id or ""),
        estimated_seconds=new_seconds,
        updated_at=_utcnow(),
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[CourseProgressRow.user_id, CourseProgressRow.scene_id],
        set_={
            "attempts": CourseProgressRow.attempts + 1,
            "cleared": or_(CourseProgressRow.cleared, literal(bool(cleared))),
            "best_total": case(
                (new_best > CourseProgressRow.best_total, new_best),
                else_=CourseProgressRow.best_total,
            ),
            "last_stage": str(last_stage or ""),
            "last_session_id": str(session_id or ""),
            "estimated_seconds": CourseProgressRow.estimated_seconds + new_seconds,
            "updated_at": _utcnow(),
        },
    )
    await db.execute(stmt)


async def load_progress_map(db: AsyncSession, user_id: str) -> dict[str, CourseProgress]:
    """画廊三字段 (cleared/best_total/attempts) 的读模型, 键 = scene_id."""
    rows = (await db.execute(_select_rows(user_id))).scalars().all()
    return {
        row.scene_id: CourseProgress(
            cleared=bool(row.cleared),
            best_total=float(row.best_total),
            attempts=int(row.attempts),
        )
        for row in rows
    }


async def list_rows(db: AsyncSession, user_id: str) -> list[CourseProgressRow]:
    """``GET /courses/progress`` 的全列行 (含 last_stage/estimated_seconds)."""
    return list((await db.execute(_select_rows(user_id))).scalars().all())


def _select_rows(user_id: str) -> Any:
    return (
        select(CourseProgressRow)
        .where(CourseProgressRow.user_id == user_id)
        .order_by(CourseProgressRow.scene_id.asc())
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["list_rows", "load_progress_map", "record_finished_session"]

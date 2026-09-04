"""个人表达库 CRUD (计划 §5.7, 表在 M2 由 T4 落地).

润色出来的「更好说法」收进库里复用 (§一 能力 4: 「可收藏进个人表达库复用」):

* ``GET  /expressions?device_id=``  列表 (新的在前, 卡片数据 = 原句/润色句/解释/来源);
* ``POST /expressions``             收藏 / 去重 upsert: **同一用户同一归一化润色句
  只存一条** (§5.7 normalized 去重), 重复收藏返回既有行 (200 + ``created=false``);
* ``DELETE /expressions/{id}``      删除自己的条目 (404 不存在 / 403 别人的)。

``source_label`` 取值 (§5.7 source labels):
``manual`` (UI 手敲) | ``polish`` (独立润色收藏) | ``mission`` (实战轮润色) |
``dialogue`` (自由对话轮润色)。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.models.db import Expression
from app.services import users

router = APIRouter(tags=["expressions"])

#: 允许的收藏来源标签 (§5.7); 未知取值按 manual 收敛, 不炸.
SOURCE_LABELS = ("manual", "polish", "mission", "dialogue")

_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^0-9a-z' ]+")


def normalize_text(text: str) -> str:
    """去重键: 小写 + 标点按空白折叠 + 压空白. ``Can I go, ok?`` == ``can i go ok``.

    标点子成空格 (而不是删掉): ``Can-I`` 归一化成 ``can i`` 而不是 ``cani`` —— 否则
    连字符写法与空格写法会收成两条卡片。撇号保留 (``it's`` 不被撕开)。
    """
    folded = _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", text.strip().lower()))
    return folded.strip()[:512]


class ExpressionDto(BaseModel):
    id: str
    polished: str
    original: str = ""
    explanation_cn: str = ""
    source_label: str = "manual"
    scene_id: str = ""
    session_id: str = ""
    created_at: str = ""


class CreateExpressionRequest(BaseModel):
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=36)
    polished: str = Field(min_length=1, max_length=1000)
    original: str = Field(default="", max_length=1000)
    explanation_cn: str = Field(default="", max_length=1000)
    source_label: str = Field(default="manual", max_length=32)
    scene_id: str = Field(default="", max_length=64)
    session_id: str = Field(default="", max_length=36)


class CreateExpressionResponse(BaseModel):
    expression: ExpressionDto
    #: False = 归一化后撞了已有条目 (去重命中, 返回既有的那条).
    created: bool


async def upsert_expression(
    db: AsyncSession,
    *,
    user_id: str,
    polished: str,
    original: str = "",
    explanation_cn: str = "",
    source_label: str = "manual",
    scene_id: str = "",
    session_id: str = "",
) -> tuple[Expression, bool]:
    """按 (user_id, normalized) 去重的收藏: 命中返回既有行 (created=False).

    并发下两个请求同时 miss 唯一索引 -> 后落库者撞 ``IntegrityError``: 回滚后
    重读赢家的那条, 语义仍是"去重命中"。**不 commit** —— 交给端点收尾。
    """
    key = normalize_text(polished) or polished.strip()[:512]
    existing = (
        await db.execute(
            select(Expression).where(Expression.user_id == user_id, Expression.normalized == key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    row = Expression(
        user_id=user_id,
        polished=polished.strip()[:1000],
        original=original.strip()[:1000],
        explanation_cn=explanation_cn.strip()[:1000],
        source_label=source_label if source_label in SOURCE_LABELS else "manual",
        scene_id=scene_id[:64],
        session_id=session_id[:36],
        normalized=key,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        winner = (
            await db.execute(
                select(Expression).where(
                    Expression.user_id == user_id, Expression.normalized == key
                )
            )
        ).scalar_one()
        return winner, False
    return row, True


def _to_dto(row: Expression) -> ExpressionDto:
    created: datetime = row.created_at
    if created.tzinfo is None:  # sqlite 剥 tzinfo, 按 UTC 解释 (同 course_sessions)
        created = created.replace(tzinfo=UTC)
    return ExpressionDto(
        id=str(row.id),
        polished=str(row.polished),
        original=str(row.original or ""),
        explanation_cn=str(row.explanation_cn or ""),
        source_label=str(row.source_label or "manual"),
        scene_id=str(row.scene_id or ""),
        session_id=str(row.session_id or ""),
        created_at=created.astimezone(UTC).isoformat(),
    )


@router.get("/expressions", response_model=list[ExpressionDto])
async def list_expressions(
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[ExpressionDto]:
    """表达库列表 (最近收藏在前). 未知 device 返回空列表, 不建用户."""
    users.require_identity(device_id, user_id)
    user = await users.lookup_user(db, device_id=device_id, user_id=user_id)
    if user is None:
        return []
    rows = (
        (
            await db.execute(
                select(Expression)
                .where(Expression.user_id == user.id)
                .order_by(Expression.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_to_dto(row) for row in rows]


@router.post("/expressions")
async def create_expression(
    req: CreateExpressionRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """收藏一条润色句 (§5.7).

    201 = 新增; 去重命中 = 200 + ``created=false`` + 既有条目 (重复点收藏按钮安全).
    """
    users.require_identity(req.device_id, req.user_id)
    user = await users.lookup_user(
        db, device_id=req.device_id, user_id=req.user_id, create=bool(req.device_id)
    )
    if user is None:
        raise AppError(404, f"unknown user_id: {req.user_id}", "USER_NOT_FOUND")
    polished = req.polished.strip()
    if not polished:
        raise AppError(400, "polished text is required", "EXPRESSION_TEXT_REQUIRED")
    row, created = await upsert_expression(
        db,
        user_id=user.id,
        polished=polished,
        original=req.original,
        explanation_cn=req.explanation_cn,
        source_label=req.source_label,
        scene_id=req.scene_id,
        session_id=req.session_id,
    )
    if created:
        await db.commit()
    payload = CreateExpressionResponse(expression=_to_dto(row), created=created)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content=payload.model_dump(mode="json"),
    )


@router.delete("/expressions/{expression_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expression(
    expression_id: str,
    device_id: str | None = Query(default=None, min_length=1, max_length=128),
    user_id: str | None = Query(default=None, min_length=1, max_length=36),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删自己的一条收藏; 不存在 404, 别人的 403."""
    users.require_identity(device_id, user_id)
    user = await users.lookup_user(db, device_id=device_id, user_id=user_id)
    if user is None:
        raise AppError(403, "unknown learner", "FORBIDDEN_EXPRESSION")
    row = (
        await db.execute(select(Expression).where(Expression.id == expression_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError(404, f"expression {expression_id} not found", "EXPRESSION_NOT_FOUND")
    if row.user_id != user.id:
        raise AppError(403, "this expression belongs to another learner", "FORBIDDEN_EXPRESSION")
    await db.delete(row)
    await db.commit()


__all__ = [
    "SOURCE_LABELS",
    "CreateExpressionRequest",
    "CreateExpressionResponse",
    "ExpressionDto",
    "normalize_text",
    "upsert_expression",
]

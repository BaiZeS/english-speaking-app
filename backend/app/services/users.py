"""按 device_id / user_id 定位 v2.0 账号 (P3 起多个 router 共用).

v2.0 仍是 device_id 账号体系 (计划 §十二: 不做账号), 一个 device 就是一个 user。
这里收口三种查法, 语义刻意分开:

* :func:`lookup_user` — **只查不注册** (``GET /ability`` / session 恢复这类读侧:
  不能让陌生 id 在库里生出用户行);  ``create=True`` 时 (写侧端点, 如
  ``POST /history`` / P3 的自由对话画像 / P3 的 collect) 才允许按 device 找/建。
* ``api/v1/course_sessions`` 里保留了它自己的 ``_lookup_user``/``_resolve_user``
  (身份来自请求体模型, T3 已钉测试, 不动)。

并发下同一 device 同时首次注册会撞 ``users.device_id`` 唯一索引: 后写者回滚后
重读 (``history.py`` / ``course_sessions.py`` 都踩过, 这里带上同样的兜底)。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.db import User


async def _get_or_create_user(db: AsyncSession, device_id: str) -> User:
    res = await db.execute(select(User).where(User.device_id == device_id))
    user = res.scalar_one_or_none()
    if user is None:
        candidate = User(device_id=device_id)
        db.add(candidate)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            res = await db.execute(select(User).where(User.device_id == device_id))
            user = res.scalar_one()
        else:
            user = candidate
    return user


async def lookup_user(
    db: AsyncSession,
    *,
    device_id: str | None = None,
    user_id: str | None = None,
    create: bool = False,
) -> User | None:
    """按身份定位用户; 找不到返回 ``None`` (``create`` 只对 device_id 生效)."""
    if user_id:
        res = await db.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if user is None and create:
            raise AppError(404, f"unknown user_id: {user_id}", "USER_NOT_FOUND")
        return user
    if device_id:
        if create:
            return await _get_or_create_user(db, device_id)
        res = await db.execute(select(User).where(User.device_id == device_id))
        return res.scalar_one_or_none()
    return None


def require_identity(device_id: str | None, user_id: str | None) -> None:
    """两个身份字段都不给 -> 统一的 400 (错误码与 course_sessions 一致)."""
    if not device_id and not user_id:
        raise AppError(400, "device_id or user_id is required", "IDENTITY_REQUIRED")


__all__ = ["lookup_user", "require_identity"]

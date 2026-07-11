"""SQLAlchemy 异步引擎与 sessionmaker 工厂。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = settings.database_url
    connect_args: dict[str, Any] = {}
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        # check_same_thread for aiosqlite's background thread; StaticPool shares
        # one connection so an in-memory sqlite db is visible across eng.begin()
        # and sessions (used by the test suite).
        connect_args = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    return create_async_engine(
        url, future=True, pool_pre_ping=True, connect_args=connect_args, **kwargs
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)

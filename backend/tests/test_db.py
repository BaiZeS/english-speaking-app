"""SQLAlchemy async engine 与 sessionmaker 测试。"""
from __future__ import annotations

import pytest

from app.db.session import get_engine, get_sessionmaker


@pytest.mark.asyncio
async def test_engine_and_sessionmaker_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    eng = get_engine()
    sm = get_sessionmaker()
    assert eng is not None
    assert sm is not None

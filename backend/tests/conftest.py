from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.db.base import Base
from app.db.session import get_engine, get_sessionmaker
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _init_db() -> AsyncIterator[None]:
    """Create all tables in fresh in-memory sqlite for each test."""
    # Both caches must be cleared: get_sessionmaker binds to the engine at
    # creation, so a stale sessionmaker would point at a disposed engine.
    get_engine.cache_clear()  # type: ignore[attr-defined]
    get_sessionmaker.cache_clear()  # type: ignore[attr-defined]
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await eng.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    sm = get_sessionmaker()

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with sm() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Bare AsyncSession into the same in-memory sqlite the autouse fixture creates.

    The client fixture overrides get_db on the app, so use this for tests
    that need to seed rows directly (e.g. timestamp-sensitive aggregations)."""
    sm = get_sessionmaker()
    async with sm() as session:
        yield session

from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.config import Settings, settings
from app.db.base import Base
from app.db.session import get_engine, get_sessionmaker
from app.main import app

# 部署可调字段: 生产机 backend/.env (env-first OTA、LLM 白名单/目录) 或 shell
# export 会把部署值漏进共享的 settings 单例, 必须逐用例强制回代码默认值.
# 新增此类字段一律加进清单 (**只增不减**); 需要非默认值的用例在测试体内自行
# monkeypatch (运行于 autouse 之后), 彼此不冲突.
_HERMETIC_CREDENTIAL_FIELDS = (
    "mimo_api_key",
    "xunfei_app_id",
    "xunfei_api_key",
    "xunfei_api_secret",
    "llm_api_key",
    "openai_api_key",
    "aliyun_dashscope_key",
)
_HERMETIC_TUNING_FIELDS = (
    "app_latest_version",
    "app_apk_url",
    "app_release_notes",
    "app_min_supported_version",
    "app_github_repo",
    "app_github_token",
    "app_github_asset_name",
    "app_github_asset_glob",
    "llm_base_url",
    "llm_default_model",
    "llm_allowed_models",
    "llm_extra_models_json",
)
_HERMETIC_DEFAULTS = {
    field: Settings.model_fields[field].default
    for field in (*_HERMETIC_CREDENTIAL_FIELDS, *_HERMETIC_TUNING_FIELDS)
}


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制 stub + 清盒路径: 测试不得依赖本机部署配置, 也不得触达外部服务."""
    for field, default in _HERMETIC_DEFAULTS.items():
        monkeypatch.setattr(settings, field, default, raising=False)


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

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
    # 讯飞单次调用硬顶: 同步路径的时延求和把它当"同请求内其它 await"算进预算
    # (tests/test_latency_budget.py), 部署改大它不能让求和测试悄悄变绿/变红.
    "xunfei_ise_timeout_s",
    "xunfei_iat_timeout_s",
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


@pytest.fixture(autouse=True)
def _no_detached_thread_grading_jobs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """v3.0 每轮评分作业不真的 ``create_task`` 派生 —— 口径与其余作业替身完全一致.

    * 断言"这一轮派生了判分作业"的用例: 直接用本 fixture 返回的调用清单;
    * 断言判分终态的用例: 自己 ``await thread_grading.run_thread_grading_job(id, uid)``。

    让它真跑起来会在用例结束、内存 sqlite 被 dispose 之后再去开一个 AsyncSession,
    收到的报错长得像"数据库坏了" (同 ``_no_detached_scene_brief_jobs`` 记的那次踩坑);
    更糟的是它会和用例自己的直接调用**抢同一颗评分卡**。
    """
    from app.api.v1 import dialogue_threads

    spawned: list[str] = []
    monkeypatch.setattr(
        dialogue_threads.thread_grading,
        "spawn_thread_grading",
        lambda tid, uid: spawned.append(tid),
    )
    return spawned


@pytest.fixture(autouse=True)
def _no_detached_scene_brief_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """自定义场景骨架作业 (§3 C3) 同理不真的 ``create_task`` 派生 —— 口径与上面三个替身完全一致.

    * 断言"202 派生了场景作业"的用例: 自己 monkeypatch 记调用;
    * 断言作业终态的用例: 直接 ``await scene_spec_generator.run_scene_brief_job(job_id)``
      —— 同 ``test_grading_async`` / ``test_course_generator`` 的手法。
    """
    from app.services import scene_spec_generator

    monkeypatch.setattr(scene_spec_generator, "spawn_scene_brief_job", lambda job_id: None)


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

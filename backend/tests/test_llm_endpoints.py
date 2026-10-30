"""Tests for /api/v1/llm/models, /api/v1/app/version, and dialogue LLM fallback paths."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.services import llm_provider


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    """Make sure tests don't leak the cached provider across env mutations."""
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.mark.asyncio
async def test_thread_turn_honors_an_allowed_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """客户端选的模型在**目录内**就被尊重 —— 接缝从旧的 ``/dialogue/generate`` 换到群聊轮。

    台词是纯文本用途, 允许跟随 ``model_id`` (D2); 判分不吃它 (恒服务端默认), 那是另一条
    路的纪律。
    """
    from tests.test_drill_grader import install_llm

    client = install_llm(
        monkeypatch,
        generation=[json.dumps({"reply": "How was your weekend?", "reply_cn": "周末过得如何?"})],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        opened = await c.post(
            "/api/v1/dialogue/threads",
            json={"scene_key": "small_talk"},
            params={"device_id": "dev-model"},
        )
        assert opened.status_code == 201, opened.text
        res = await c.post(
            f"/api/v1/dialogue/threads/{opened.json()['id']}/turn",
            json={"mode": "text", "text": "It was good", "model_id": "qwen-turbo"},
            params={"device_id": "dev-model"},
        )
        assert res.status_code == 200, res.text
    assert client.requests[-1]["model"] == "qwen-turbo"


@pytest.mark.asyncio
async def test_thread_turn_rejects_an_unlisted_model_id_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不在目录里的 ``model_id`` 回落到服务端默认, 而不是 400 —— 老客户端可能还在传历史值。"""
    from tests.test_drill_grader import install_llm

    client = install_llm(
        monkeypatch,
        generation=[json.dumps({"reply": "Any plans this weekend?", "reply_cn": "周末有安排吗?"})],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        opened = await c.post(
            "/api/v1/dialogue/threads",
            json={"scene_key": "small_talk"},
            params={"device_id": "dev-ghost"},
        )
        res = await c.post(
            f"/api/v1/dialogue/threads/{opened.json()['id']}/turn",
            json={"mode": "text", "text": "No plans", "model_id": "gpt-9-mega"},
            params={"device_id": "dev-ghost"},
        )
        assert res.status_code == 200, res.text
    assert client.requests[-1]["model"] != "gpt-9-mega"


@pytest.mark.asyncio
async def test_llm_models_returns_static_catalog_by_default() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/llm/models")
    assert r.status_code == 200
    data = r.json()
    ids = [m["id"] for m in data["models"]]
    assert "qwen-plus" in ids
    assert "qwen-turbo" in ids
    assert data["default_model"]


@pytest.mark.asyncio
async def test_llm_models_honors_allow_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_allowed_models", "qwen-turbo,deepseek-v3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/llm/models")
    ids = [m["id"] for m in r.json()["models"]]
    assert set(ids) == {"qwen-turbo", "deepseek-v3"}


@pytest.mark.asyncio
async def test_app_version_endpoint_returns_configured_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_latest_version", "1.2.3")
    monkeypatch.setattr(settings, "app_min_supported_version", "1.0.0")
    monkeypatch.setattr(settings, "app_apk_url", "https://example.com/app.apk")
    monkeypatch.setattr(settings, "app_release_notes", "新增自由对话模型选择")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/app/version")
    data = r.json()
    assert data["latest_version"] == "1.2.3"
    assert data["min_supported_version"] == "1.0.0"
    assert data["apk_url"] == "https://example.com/app.apk"
    assert "自由对话" in data["release_notes"]
    assert data["force_update"] is True


@pytest.mark.asyncio
async def test_app_version_force_update_false_when_min_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P8 强更 bug 回归: env 未配置时 min_supported 不能等于 latest.

    旧默认 (min = latest) 让所有旧包 (客户端判 current < min → 必弹且「稍后再说」
    无效) 陷入不可跳过的更新弹窗, 与计划 §九.5 「OTA 对 1.4.0 正常提示且不强制」
    矛盾。未配置 = 0.0.0 哨兵 (没有版本被判不支持), 弹窗回到可跳过的常规路径。
    """
    monkeypatch.setattr(settings, "app_latest_version", "2.0.0")
    monkeypatch.setattr(settings, "app_min_supported_version", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/app/version")
    data = r.json()
    assert data["force_update"] is False
    assert data["min_supported_version"] == "0.0.0"

"""Tests for /api/v1/llm/models, /api/v1/app/version, and dialogue LLM fallback paths."""

from __future__ import annotations

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
    monkeypatch.setattr(settings, "app_latest_version", "1.0.0")
    monkeypatch.setattr(settings, "app_min_supported_version", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/app/version")
    assert r.json()["force_update"] is False


@pytest.mark.asyncio
async def test_dialogue_generate_falls_back_to_stub_without_credentials() -> None:
    payload = {"scene": "daily_conversation", "mode": "adult", "model_id": "qwen-plus"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == "stub"
    assert data["model_id"] is None


@pytest.mark.asyncio
async def test_dialogue_generate_uses_mock_llm_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stub the AsyncOpenAI client and ensure dialogue/generate consumes it."""
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")
    monkeypatch.setattr(settings, "llm_default_model", "qwen-plus")

    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = type("M", (), {"content": content})()

    class _Resp:
        model = "qwen-plus"

        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    class _Completions:
        async def create(self, **_: object) -> _Resp:
            return _Resp("Hello there! How is your day going?")

    class _Chat:
        completions = _Completions()

    captured: dict[str, object] = {}

    class _Client:
        def with_options(self, **kwargs: object) -> _Client:
            captured["with_options"] = kwargs
            return self

        @property
        def chat(self) -> _Chat:
            return _Chat()

    async def _factory(**_: object) -> _Client:
        return _Client()

    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "AsyncOpenAI", _factory)
    llm_provider.reset_llm_provider_for_tests()

    payload = {"scene": "daily_conversation", "mode": "adult", "model_id": "qwen-turbo"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == "ready"
    assert data["model_id"] == "qwen-plus"  # qwen-turbo is not in default catalog -> fallback
    assert "How is your day" in data["lines"][0]["text"]


@pytest.mark.asyncio
async def test_dialogue_turn_parses_llm_json_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")
    monkeypatch.setattr(settings, "llm_default_model", "qwen-plus")

    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = type("M", (), {"content": content})()

    class _Resp:
        model = "qwen-plus"

        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    class _Completions:
        async def create(self, **_: object) -> _Resp:
            return _Resp('{"reply": "Great!", "suggestion": "I am glad to hear that."}')

    class _Chat:
        completions = _Completions()

    class _Client:
        def with_options(self, **_: object) -> _Client:
            return self

        @property
        def chat(self) -> _Chat:
            return _Chat()

    async def _factory(**_: object) -> _Client:
        return _Client()

    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "AsyncOpenAI", _factory)
    llm_provider.reset_llm_provider_for_tests()

    payload = {
        "scene_id": "daily_conversation",
        "history": [
            {"role": "assistant", "text": "Hi!"},
            {"role": "user", "text": "I am fine."},
        ],
        "model_id": "qwen-plus",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == "ready"
    assert data["reply_text"] == "Great!"
    assert data["suggested_reply"] == "I am glad to hear that."
    assert data["model_id"] == "qwen-plus"


@pytest.mark.asyncio
async def test_dialogue_turn_degrades_to_stub_when_llm_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")

    class _Completions:
        async def create(self, **_: object) -> None:
            raise RuntimeError("upstream down")

    class _Chat:
        completions = _Completions()

    class _Client:
        def with_options(self, **_: object) -> _Client:
            return self

        @property
        def chat(self) -> _Chat:
            return _Chat()

    async def _factory(**_: object) -> _Client:
        return _Client()

    import app.services.llm_provider as lp

    monkeypatch.setattr(lp, "AsyncOpenAI", _factory)
    llm_provider.reset_llm_provider_for_tests()

    payload = {
        "scene_id": "daily_conversation",
        "history": [{"role": "user", "text": "Hi"}],
        "model_id": "qwen-plus",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == "stub"
    assert data["model_id"] is None

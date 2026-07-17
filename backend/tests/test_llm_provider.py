"""Unit tests for the LLM provider abstraction.

These focus on the Bailian provider's behaviour: configuration gating,
fallback catalog, and tolerate-on-upstream-error semantics. The end-to-end
tests in ``test_llm_endpoints.py`` cover the dialogue endpoints.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.config import settings
from app.services import llm_provider
from app.services.llm_provider import (
    _DEFAULT_BAILIAN_MODELS,
    BailianOpenAIProvider,
    LlmMessage,
    ModelInfo,
    _parse_model_catalog,
)


@pytest.fixture(autouse=True)
def _reset_provider() -> None:
    """Drop the cached provider so each test exercises construction."""
    llm_provider.reset_llm_provider_for_tests()


def test_default_catalog_contains_expected_bailian_models() -> None:
    """The curated catalog is the source of truth for the Android UI."""
    ids = {info.id for info in _DEFAULT_BAILIAN_MODELS}
    assert {"qwen-plus", "qwen-turbo", "qwen-max", "deepseek-v3"} <= ids


def test_provider_without_credentials_is_not_configured() -> None:
    provider = BailianOpenAIProvider()
    assert provider.is_configured is False


def test_provider_default_model_falls_back_to_curated_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_default_model", "")
    provider = BailianOpenAIProvider()
    assert provider.default_model == _DEFAULT_BAILIAN_MODELS[0].id


def test_provider_with_credentials_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")
    provider = BailianOpenAIProvider()
    assert provider.is_configured is True
    assert provider._client is not None


@pytest.mark.asyncio
async def test_list_models_without_credentials_returns_curated_catalog() -> None:
    provider = BailianOpenAIProvider()
    models = await provider.list_models()
    assert models == [info.id for info in _DEFAULT_BAILIAN_MODELS]


@pytest.mark.asyncio
async def test_list_models_merges_upstream_ids_with_curated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")

    class _Model:
        def __init__(self, mid: str) -> None:
            self.id = mid

    class _ListResp:
        data: ClassVar[list[object]] = [_Model("custom-llm-a"), _Model("qwen-plus")]

    class _Models:
        async def list(self) -> _ListResp:
            return _ListResp()

    class _Client:
        models = _Models()

    provider = BailianOpenAIProvider()
    provider._client = _Client()  # type: ignore[assignment]
    models = await provider.list_models()
    # Union of upstream + curated, sorted.
    assert "custom-llm-a" in models
    assert "qwen-plus" in models
    assert models == sorted(set(models))


@pytest.mark.asyncio
async def test_list_models_falls_back_when_upstream_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")

    class _ListResp:
        data: ClassVar[list[object]] = []

    class _Models:
        async def list(self) -> _ListResp:
            return _ListResp()

    class _Client:
        models = _Models()

    provider = BailianOpenAIProvider()
    provider._client = _Client()  # type: ignore[assignment]
    models = await provider.list_models()
    assert models == [info.id for info in _DEFAULT_BAILIAN_MODELS]


@pytest.mark.asyncio
async def test_list_models_degrades_on_upstream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.com/v1")

    class _Models:
        async def list(self) -> None:
            raise RuntimeError("upstream timeout")

    class _Client:
        models = _Models()

    provider = BailianOpenAIProvider()
    provider._client = _Client()  # type: ignore[assignment]
    models = await provider.list_models()
    assert models == [info.id for info in _DEFAULT_BAILIAN_MODELS]


@pytest.mark.asyncio
async def test_chat_without_client_raises() -> None:
    provider = BailianOpenAIProvider()
    with pytest.raises(RuntimeError, match="not configured"):
        await provider.chat(model="qwen-plus", messages=[LlmMessage(role="user", content="hi")])


def test_parse_catalog_ignores_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_extra_models_json", "{not json}")
    catalog = _parse_model_catalog()
    # Falls back to curated only.
    assert {info.id for info in catalog} == {info.id for info in _DEFAULT_BAILIAN_MODELS}


def test_parse_catalog_ignores_non_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_extra_models_json", '{"id":"x"}')
    catalog = _parse_model_catalog()
    assert {info.id for info in catalog} == {info.id for info in _DEFAULT_BAILIAN_MODELS}


def test_parse_catalog_appends_valid_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "llm_extra_models_json",
        '[{"id":"custom","display_name":"Custom","provider":"self","description":"local"},'
        '{"missing_id":true}]',
    )
    catalog = _parse_model_catalog()
    ids = {info.id for info in catalog}
    assert "custom" in ids
    # The malformed entry is skipped silently.
    assert len(catalog) == len(_DEFAULT_BAILIAN_MODELS) + 1
    custom = next(info for info in catalog if info.id == "custom")
    assert isinstance(custom, ModelInfo)
    assert custom.provider == "self"


def test_get_model_catalog_returns_fresh_list() -> None:
    """Mutating the returned list must not bleed into subsequent calls."""
    catalog_a = llm_provider.get_model_catalog()
    catalog_a.clear()
    catalog_b = llm_provider.get_model_catalog()
    assert len(catalog_b) == len(_DEFAULT_BAILIAN_MODELS)

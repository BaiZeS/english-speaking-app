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


# ============================================================ P3: 模型回退链修正
#
# 背景 (T2 发现的缺陷, T4 落地): 旧链在 ``LLM_ALLOWED_MODELS``/``LLM_DEFAULT_MODEL``
# 都没配时回落硬编码的 qwen-plus —— 该系模型 2026-08 实测配额全 403, 链尾藏一个
# 会过期的模型 id 等于埋雷。现在全链由配置驱动且**确定性排序** (旧的
# ``next(iter(set))`` 会随哈希随机化)。判分走 ``resolve_server_default_model``,
# 人设/润色文本走 ``resolve_roleplay_model`` (客户端 id 必须过白名单)。


def _clear_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_default_model", "")
    monkeypatch.setattr(settings, "llm_allowed_models", "")
    monkeypatch.setattr(settings, "llm_extra_models_json", "")


def test_config_default_is_empty_not_a_hardcoded_dead_model() -> None:
    """代码出厂默认必须是空串 —— 具体模型 id 属于运维配置 (.env / docker env)."""
    from app.config import Settings

    assert Settings.model_fields["llm_default_model"].default == ""


def test_server_default_follows_llm_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_default_model", "my-model")
    assert llm_provider.resolve_server_default_model() == "my-model"
    provider = BailianOpenAIProvider()
    assert provider.default_model == "my-model"


def test_server_default_falls_back_to_first_allowed_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_allowed_models", "b-first,a-second")
    # 顺序就是配置里的顺序 (确定性; 不是 set 的哈希序)
    assert llm_provider.allowed_model_ids() == ["b-first", "a-second"]
    assert llm_provider.resolve_server_default_model() == "b-first"


def test_server_default_last_resort_is_first_catalog_entry_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_settings(monkeypatch)
    expect = _DEFAULT_BAILIAN_MODELS[0].id
    for _ in range(5):  # 重跑不变 (旧实现按 set 迭代, 结果不稳定)
        assert llm_provider.resolve_server_default_model() == expect


def test_roleplay_model_honors_allowlisted_client_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_default_model", "server-default")
    monkeypatch.setattr(settings, "llm_allowed_models", "a,b")
    assert llm_provider.resolve_roleplay_model("b") == "b"
    assert llm_provider.resolve_roleplay_model("not-listed") == "server-default"
    assert llm_provider.resolve_roleplay_model(None) == "server-default"
    assert llm_provider.resolve_roleplay_model("   ") == "server-default"


def test_roleplay_model_without_allowlist_uses_catalog_back_compat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.4.0 客户端只会发目录内 id: 白名单没配时目录就是白名单 (add-only 兼容)."""
    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_default_model", "server-default")
    catalog_id = _DEFAULT_BAILIAN_MODELS[1].id
    assert llm_provider.resolve_roleplay_model(catalog_id) == catalog_id
    assert llm_provider.resolve_roleplay_model("anything-else") == "server-default"


def test_extra_models_join_the_roleplay_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(
        settings,
        "llm_extra_models_json",
        '[{"id":"private-gpt","display_name":"内网","provider":"self","description":"x"}]',
    )
    assert llm_provider.resolve_roleplay_model("private-gpt") == "private-gpt"


def test_dialogue_resolve_model_delegates_to_provider_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api 侧 ``_resolve_model`` 不再是第二套链: 全部收口到 llm_provider."""
    from app.api.v1.dialogue import _resolve_model

    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_allowed_models", "solo")
    assert _resolve_model("solo") == "solo"
    assert _resolve_model("ghost") == "solo"  # default 链: 无 default -> 首个 ALLOWED
    assert _resolve_model(None) == "solo"


@pytest.mark.asyncio
async def test_unconfigured_deployment_never_resolves_by_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全空配置 (CI 的 .env 缺失形态): 解析仍返回确定性字符串, 不 IndexError."""
    _clear_model_settings(monkeypatch)
    assert isinstance(llm_provider.resolve_server_default_model(), str)
    assert llm_provider.resolve_server_default_model()


def test_grading_model_helper_follows_server_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """判分模型恒跟服务端默认: ``drill_grader._resolve_judge_model`` 不碰 request."""
    from app.services.drill_grader import _resolve_judge_model

    _clear_model_settings(monkeypatch)
    monkeypatch.setattr(settings, "llm_default_model", "grader-model")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    assert _resolve_judge_model() == "grader-model"

"""Unit tests for the AppVersionResolver (GitHub Releases + env fallback)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from app.config import settings
from app.services import app_version_resolver
from app.services.app_version_resolver import (
    AppVersionResolver,
    ResolvedVersion,
    _pick_apk_asset,
    get_app_version_resolver,
)


@pytest.fixture(autouse=True)
def _reset_resolver() -> Iterator[None]:
    """Each test starts with no cached resolver or memoized payload."""
    app_version_resolver.reset_app_version_resolver_for_tests()
    yield
    app_version_resolver.reset_app_version_resolver_for_tests()


class _StubTransport(httpx.MockTransport):
    """Minimal transport stub capturing the last call and returning canned JSON."""

    def __init__(self) -> None:
        super().__init__(self._handle)
        self.payload: dict[str, object] = {}
        self.status_code: int = 200
        self.calls: list[str] = []
        self.last_headers: dict[str, str] | None = None

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        self.last_headers = dict(request.headers)
        return httpx.Response(self.status_code, json=self.payload)


def _build_resolver_with_transport(
    transport: _StubTransport,
    cache_ttl: float = 300.0,
) -> AppVersionResolver:
    """Wire a MockTransport-backed AsyncClient straight into the resolver.

    Avoids the monkeypatch-on-httpx.AsyncClient pattern, which proved flaky
    under pytest-asyncio: the resolver runs in a fresh event loop per test
    but pytest's monkeypatch can be reset between collections in ways the
    factory callback didn't survive. Direct injection is simpler and
    deterministic.
    """

    def _client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport)

    return AppVersionResolver(http_client_factory=_client_factory, cache_ttl=cache_ttl)


# ---------- env precedence -------------------------------------------------


@pytest.mark.asyncio
async def test_env_override_skips_github_even_when_repo_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_latest_version", "1.2.0")
    monkeypatch.setattr(settings, "app_apk_url", "https://mirror.example.com/app.apk")
    transport = _StubTransport()
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "1.2.0"
    assert resolved.apk_url == "https://mirror.example.com/app.apk"
    assert resolved.source == "env"
    assert transport.calls == []  # never hit the network


@pytest.mark.asyncio
async def test_github_used_when_env_apk_url_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_apk_url", "")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.3.0",
        "body": "新增自动更新",
        "assets": [
            {
                "name": "app-debug.apk",
                "browser_download_url": "https://github.com/.../app-debug.apk",
            }
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "1.3.0"
    assert resolved.apk_url == "https://github.com/.../app-debug.apk"
    assert resolved.release_notes == "新增自动更新"
    assert resolved.source == "github"


@pytest.mark.asyncio
async def test_default_when_no_repo_and_no_env_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "")
    monkeypatch.setattr(settings, "app_apk_url", "")
    monkeypatch.setattr(settings, "app_latest_version", "0.5.0")
    transport = _StubTransport()
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "0.5.0"
    assert resolved.apk_url == ""
    assert resolved.source == "default"
    assert transport.calls == []


# ---------- GitHub response handling ---------------------------------------


@pytest.mark.asyncio
async def test_tag_with_v_prefix_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "V2.0.0",
        "body": "",
        "assets": [
            {"name": "EnglishAssistant-2.0.0.apk", "browser_download_url": "https://x/y.apk"}
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "2.0.0"


@pytest.mark.asyncio
async def test_picks_asset_matching_glob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_github_asset_glob", "*release*.apk")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "EnglishAssistant-debug.apk", "browser_download_url": "https://x/debug.apk"},
            {
                "name": "EnglishAssistant-release.apk",
                "browser_download_url": "https://x/release.apk",
            },
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.apk_url == "https://x/release.apk"


@pytest.mark.asyncio
async def test_exact_asset_name_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_github_asset_name", "EnglishAssistant.apk")
    monkeypatch.setattr(settings, "app_github_asset_glob", "*.apk")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "app-debug.apk", "browser_download_url": "https://x/debug.apk"},
            {"name": "EnglishAssistant.apk", "browser_download_url": "https://x/ea.apk"},
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.apk_url == "https://x/ea.apk"


@pytest.mark.asyncio
async def test_no_apk_asset_returns_empty_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "checksums.txt", "browser_download_url": "https://x/sha"},
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "1.0.0"
    assert resolved.apk_url == ""


@pytest.mark.asyncio
async def test_github_404_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_latest_version", "0.4.0")
    transport = _StubTransport()
    transport.status_code = 404
    transport.payload = {"message": "Not Found"}
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "0.4.0"
    assert resolved.source == "default"


@pytest.mark.asyncio
async def test_github_5xx_falls_back_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_latest_version", "0.3.0")
    transport = _StubTransport()
    transport.status_code = 503
    resolver = _build_resolver_with_transport(transport)
    resolved = await resolver.resolve()
    assert resolved.latest_version == "0.3.0"
    assert resolved.source == "default"


@pytest.mark.asyncio
async def test_auth_header_added_when_token_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_github_token", "ghp_test")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "EnglishAssistant-1.0.0.apk", "browser_download_url": "https://x/y.apk"}
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    await resolver.resolve()
    assert transport.last_headers is not None
    assert transport.last_headers.get("authorization") == "Bearer ghp_test"


# ---------- caching --------------------------------------------------------


@pytest.mark.asyncio
async def test_result_is_cached_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "EnglishAssistant-1.0.0.apk", "browser_download_url": "https://x/y.apk"}
        ],
    }
    resolver = _build_resolver_with_transport(transport)
    first = await resolver.resolve()
    # Even if the upstream would return a new tag, the second call hits cache.
    transport.payload["tag_name"] = "v9.9.9"
    second = await resolver.resolve()
    assert first.latest_version == "1.0.0"
    assert second.latest_version == "1.0.0"
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_cache_disabled_when_ttl_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    transport = _StubTransport()
    transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "EnglishAssistant-1.0.0.apk", "browser_download_url": "https://x/y.apk"}
        ],
    }
    resolver = _build_resolver_with_transport(transport, cache_ttl=0.0)
    await resolver.resolve()
    transport.payload["tag_name"] = "v2.0.0"
    resolved = await resolver.resolve()
    assert resolved.latest_version == "2.0.0"


def test_invalidate_clears_cache() -> None:
    resolver = AppVersionResolver()
    resolver._cache = app_version_resolver._CacheEntry(
        payload=ResolvedVersion(latest_version="1.0.0", apk_url="", release_notes="", source="env"),
        fetched_at=0.0,
    )
    resolver.invalidate()
    assert resolver._cache is None


# ---------- asset selection (pure function) --------------------------------


def test_pick_apk_asset_falls_back_to_first_apk_when_no_pattern_matches() -> None:
    assets = [
        {"name": "source.zip", "browser_download_url": "https://x/src.zip"},
        {"name": "EnglishAssistant-1.2.0.apk", "browser_download_url": "https://x/ea.apk"},
    ]
    assert _pick_apk_asset(assets) == "https://x/ea.apk"


def test_pick_apk_asset_returns_empty_when_only_non_apk_assets() -> None:
    assets = [{"name": "checksums.txt", "browser_download_url": "https://x/sha"}]
    assert _pick_apk_asset(assets) == ""


def test_pick_apk_asset_ignores_empty_list() -> None:
    assert _pick_apk_asset([]) == ""


# ---------- singleton ------------------------------------------------------


def test_singleton_is_stable_across_calls() -> None:
    a = get_app_version_resolver()
    b = get_app_version_resolver()
    assert a is b

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


@pytest.fixture
def stub_transport(monkeypatch: pytest.MonkeyPatch) -> _StubTransport:
    """Inject a ``MockTransport`` into ``httpx.AsyncClient`` for the duration of the test."""
    transport = _StubTransport()
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(transport))
    return transport


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


def _client_factory(transport: httpx.MockTransport):  # type: ignore[no-untyped-def]
    def _factory(**kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return httpx.AsyncClient(**kwargs)

    return _factory


# ---------- env precedence -------------------------------------------------


@pytest.mark.asyncio
async def test_env_override_skips_github_even_when_repo_set(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_latest_version", "1.2.0")
    monkeypatch.setattr(settings, "app_apk_url", "https://mirror.example.com/app.apk")
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "1.2.0"
    assert resolved.apk_url == "https://mirror.example.com/app.apk"
    assert resolved.source == "env"
    assert stub_transport.calls == []  # never hit the network


@pytest.mark.asyncio
async def test_github_used_when_env_apk_url_empty(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_apk_url", "")  # no override
    stub_transport.payload = {
        "tag_name": "v1.3.0",
        "body": "新增自动更新",
        "assets": [
            {
                "name": "app-debug.apk",
                "browser_download_url": "https://github.com/.../app-debug.apk",
            }
        ],
    }
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "1.3.0"
    assert resolved.apk_url == "https://github.com/.../app-debug.apk"
    assert resolved.release_notes == "新增自动更新"
    assert resolved.source == "github"


@pytest.mark.asyncio
async def test_default_when_no_repo_and_no_env_url(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "")
    monkeypatch.setattr(settings, "app_apk_url", "")
    monkeypatch.setattr(settings, "app_latest_version", "0.5.0")
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "0.5.0"
    assert resolved.apk_url == ""
    assert resolved.source == "default"
    assert stub_transport.calls == []


# ---------- GitHub response handling ---------------------------------------


@pytest.mark.asyncio
async def test_tag_with_v_prefix_is_stripped(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    stub_transport.payload = {
        "tag_name": "V2.0.0",
        "body": "",
        "assets": [{"name": "app-debug.apk", "browser_download_url": "https://x/y.apk"}],
    }
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "2.0.0"


@pytest.mark.asyncio
async def test_picks_asset_matching_glob(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_github_asset_glob", "*release*.apk")
    stub_transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "app-debug.apk", "browser_download_url": "https://x/debug.apk"},
            {"name": "app-release.apk", "browser_download_url": "https://x/release.apk"},
        ],
    }
    resolved = await AppVersionResolver().resolve()
    assert resolved.apk_url == "https://x/release.apk"


@pytest.mark.asyncio
async def test_exact_asset_name_wins(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_github_asset_name", "EnglishAssistant.apk")
    monkeypatch.setattr(settings, "app_github_asset_glob", "*.apk")
    stub_transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "app-debug.apk", "browser_download_url": "https://x/debug.apk"},
            {"name": "EnglishAssistant.apk", "browser_download_url": "https://x/ea.apk"},
        ],
    }
    resolved = await AppVersionResolver().resolve()
    assert resolved.apk_url == "https://x/ea.apk"


@pytest.mark.asyncio
async def test_no_apk_asset_returns_empty_url(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    stub_transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [
            {"name": "checksums.txt", "browser_download_url": "https://x/sha"},
        ],
    }
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "1.0.0"
    assert resolved.apk_url == ""


@pytest.mark.asyncio
async def test_github_404_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_latest_version", "0.4.0")
    stub_transport.status_code = 404
    stub_transport.payload = {"message": "Not Found"}
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "0.4.0"
    assert resolved.source == "default"


@pytest.mark.asyncio
async def test_github_5xx_falls_back_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_latest_version", "0.3.0")
    stub_transport.status_code = 503
    resolved = await AppVersionResolver().resolve()
    assert resolved.latest_version == "0.3.0"
    assert resolved.source == "default"


@pytest.mark.asyncio
async def test_auth_header_added_when_token_set(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    monkeypatch.setattr(settings, "app_github_token", "ghp_test")
    stub_transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [{"name": "app-debug.apk", "browser_download_url": "https://x/y.apk"}],
    }
    await AppVersionResolver().resolve()
    assert stub_transport.last_headers is not None
    assert stub_transport.last_headers.get("Authorization") == "Bearer ghp_test"


# ---------- caching --------------------------------------------------------


@pytest.mark.asyncio
async def test_result_is_cached_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    stub_transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [{"name": "app-debug.apk", "browser_download_url": "https://x/y.apk"}],
    }
    resolver = AppVersionResolver()
    first = await resolver.resolve()
    # Even if the upstream would return a new tag, the second call hits cache.
    stub_transport.payload["tag_name"] = "v9.9.9"
    second = await resolver.resolve()
    assert first.latest_version == "1.0.0"
    assert second.latest_version == "1.0.0"
    assert len(stub_transport.calls) == 1


@pytest.mark.asyncio
async def test_cache_disabled_when_ttl_zero(
    monkeypatch: pytest.MonkeyPatch,
    stub_transport: _StubTransport,
) -> None:
    monkeypatch.setattr(settings, "app_github_repo", "BaiZeS/english-speaking-app")
    stub_transport.payload = {
        "tag_name": "v1.0.0",
        "body": "",
        "assets": [{"name": "app-debug.apk", "browser_download_url": "https://x/y.apk"}],
    }
    resolver = AppVersionResolver(cache_ttl=0.0)
    await resolver.resolve()
    stub_transport.payload["tag_name"] = "v2.0.0"
    resolved = await resolver.resolve()
    assert resolved.latest_version == "2.0.0"


def test_invalidate_clears_cache() -> None:
    resolver = AppVersionResolver()
    # Internal access for the test; mirroring the production module behavior.
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

"""Resolve the latest APK version + download URL.

Precedence:
  1. Explicit ``APP_APK_URL`` / ``APP_LATEST_VERSION`` in the environment —
     always wins, useful for self-hosted deployments or staged rollouts.
  2. ``APP_GITHUB_REPO`` (e.g. ``"BaiZeS/english-speaking-app"``) — falls
     back to the GitHub Releases API, picks the latest non-prerelease
     release, and selects the APK asset whose name matches the configured
     ``APP_GITHUB_ASSET_GLOB`` (default ``app-debug*.apk``).
  3. ``APP_LATEST_VERSION`` alone with an empty ``APP_APK_URL`` — returns
     the version but no URL so the dialog can still render but the download
     button stays disabled.

Results are memoised in-process for ``CACHE_TTL_SECONDS`` to stay well
under the GitHub API's unauthenticated 60 req/h/IP rate limit.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from app.config import settings

# TTL is short on purpose: we want the user to see a new release within a
# few minutes of tagging. Long enough to absorb a /app/version burst from
# freshly-launched clients, short enough that the dialog picks up rollbacks.
CACHE_TTL_SECONDS = 300.0

# GitHub API base; we deliberately pin the version so a future breaking
# change doesn't silently alter the payload we parse.
_GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class ResolvedVersion:
    latest_version: str
    apk_url: str
    release_notes: str
    source: str  # "env" | "github" | "default"


@dataclass
class _CacheEntry:
    payload: ResolvedVersion
    fetched_at: float


class AppVersionResolver:
    """Resolve the latest APK version, env-first then GitHub."""

    def __init__(
        self,
        *,
        cache_ttl: float = CACHE_TTL_SECONDS,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._cache_ttl = cache_ttl
        self._cache: _CacheEntry | None = None
        self._lock = asyncio.Lock()
        # Tests can inject a MockTransport-backed client by passing a
        # factory here; production leaves it None and we open a fresh
        # httpx.AsyncClient per request.
        self._http_client_factory = http_client_factory

    async def resolve(self) -> ResolvedVersion:
        """Return the latest version, preferring explicit env over GitHub."""
        async with self._lock:
            cached = self._cache
            if cached is not None and (time.monotonic() - cached.fetched_at) < self._cache_ttl:
                return cached.payload

        explicit = self._from_env()
        # Only treat env as an override when the operator explicitly set the
        # APK URL — that's the real signal of "self-hosted / staged rollout".
        # The default app_latest_version="1.0.0" placeholder must NOT
        # short-circuit the GitHub lookup; otherwise the resolver would
        # happily return 1.0.0 + empty URL forever.
        if explicit.apk_url:
            payload = explicit
        else:
            payload = await self._from_github_or_default()

        async with self._lock:
            self._cache = _CacheEntry(payload=payload, fetched_at=time.monotonic())
        return payload

    def invalidate(self) -> None:
        """Drop the cache. Hook for ops/tests that need a fresh fetch."""
        self._cache = None

    # --- internals ----------------------------------------------------------

    def _from_env(self) -> ResolvedVersion:
        """Read the explicit env override. Empty ``apk_url`` is preserved so the
        resolver knows to fall through to GitHub if the operator only set the
        version."""
        return ResolvedVersion(
            latest_version=settings.app_latest_version or "0.0.0",
            apk_url=settings.app_apk_url,
            release_notes=settings.app_release_notes,
            source="env",
        )

    async def _from_github_or_default(self) -> ResolvedVersion:
        repo = settings.app_github_repo.strip()
        if not repo:
            return ResolvedVersion(
                latest_version=settings.app_latest_version or "0.0.0",
                apk_url=settings.app_apk_url,
                release_notes=settings.app_release_notes,
                source="default",
            )
        try:
            return await self._fetch_github(repo)
        except Exception as exc:
            logger.warning("GitHub Releases lookup failed; using env defaults. err={}", exc)
            return ResolvedVersion(
                latest_version=settings.app_latest_version or "0.0.0",
                apk_url=settings.app_apk_url,
                release_notes=settings.app_release_notes,
                source="default",
            )

    async def _fetch_github(self, repo: str) -> ResolvedVersion:
        url = f"{_GITHUB_API}/repos/{repo}/releases/latest"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = settings.app_github_token.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Tests inject a pre-built client (MockTransport-backed); production
        # builds a fresh one per request. We never share state across calls.
        client_cm = (
            self._http_client_factory()
            if self._http_client_factory is not None
            else httpx.AsyncClient(timeout=15.0)
        )
        async with client_cm as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                logger.info("GitHub repo {} has no published releases yet", repo)
                # Surface the env fallback so operators can still see the
                # "you forgot to publish" case via a non-zero version.
                return ResolvedVersion(
                    latest_version=settings.app_latest_version or "0.0.0",
                    apk_url=settings.app_apk_url,
                    release_notes=settings.app_release_notes,
                    source="default",
                )
            response.raise_for_status()

        release = response.json()
        tag = str(release.get("tag_name") or "").lstrip("vV") or "0.0.0"
        notes = str(release.get("body") or "")
        apk_url = _pick_apk_asset(release.get("assets") or [])
        if not apk_url:
            logger.info("GitHub release {} has no matching APK asset", tag)
        return ResolvedVersion(
            latest_version=tag,
            apk_url=apk_url,
            release_notes=notes,
            source="github",
        )


def _pick_apk_asset(assets: list[dict[str, Any]]) -> str:
    """Pick the most relevant APK asset from a release payload.

    Preference order:
      1. exact match on ``APP_GITHUB_ASSET_NAME``
      2. fnmatch on ``APP_GITHUB_ASSET_GLOB`` (case-insensitive)
      3. any ``*.apk`` (fallback)
    """
    if not assets:
        return ""
    apks = [a for a in assets if str(a.get("name", "")).lower().endswith(".apk")]
    if not apks:
        return ""

    exact = settings.app_github_asset_name.strip()
    if exact:
        for asset in apks:
            if asset.get("name") == exact:
                return str(asset.get("browser_download_url", ""))

    pattern = settings.app_github_asset_glob.strip() or "*.apk"
    for asset in apks:
        if fnmatch.fnmatchcase(str(asset.get("name", "")), pattern):
            return str(asset.get("browser_download_url", ""))
    # Last resort: first APK we see, no filtering.
    return str(apks[0].get("browser_download_url", ""))


# ---------- module-level singleton ----------


_resolver: AppVersionResolver | None = None


def get_app_version_resolver() -> AppVersionResolver:
    """Return the process-wide resolver. Lazy to avoid httpx construction at import."""
    global _resolver
    if _resolver is None:
        _resolver = AppVersionResolver()
    return _resolver


def reset_app_version_resolver_for_tests() -> None:
    """Drop the cached resolver + memoized payload. Used by the test suite."""
    global _resolver
    _resolver = None

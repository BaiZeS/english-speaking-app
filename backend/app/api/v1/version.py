"""App 自动更新元数据端点.

客户端启动时拉取 ``GET /api/v1/app/version``, 与本地 BuildConfig.VERSION_NAME
比较. 后端用 ``APP_LATEST_VERSION`` (semver) + ``APP_APK_URL`` (HTTPS APK 链接)
+ ``APP_MIN_SUPPORTED_VERSION`` (强升门槛) 配置; 客户端据此弹更新对话框.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["version"])


class AppVersionResponse(BaseModel):
    latest_version: str
    min_supported_version: str
    apk_url: str
    release_notes: str
    force_update: bool


@router.get("/app/version", response_model=AppVersionResponse)
async def app_version() -> AppVersionResponse:
    """Return the latest available APK version and download URL.

    ``force_update`` is derived from whether ``min_supported_version`` is
    set: the client compares its own version against this floor and, if
    older, blocks the user until they update.
    """
    return AppVersionResponse(
        latest_version=settings.app_latest_version or "0.0.0",
        min_supported_version=settings.app_min_supported_version
        or settings.app_latest_version
        or "0.0.0",
        apk_url=settings.app_apk_url,
        release_notes=settings.app_release_notes,
        force_update=bool(settings.app_min_supported_version.strip()),
    )

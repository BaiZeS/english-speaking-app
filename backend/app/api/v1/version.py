"""App 自动更新元数据端点.

客户端启动时拉取 ``GET /api/v1/app/version``, 与本地 BuildConfig.VERSION_NAME
比较. 后端按下面的优先级回源:

  1. 显式配置 ``APP_APK_URL`` + ``APP_LATEST_VERSION`` (env 直给, 自托管场景)
  2. ``APP_GITHUB_REPO`` (e.g. ``BaiZeS/english-speaking-app``) → GitHub Releases API
  3. 默认值 (返回版本号但无下载链接, 弹窗依然能渲染)

GitHub 回源走 ``AppVersionResolver`` 的 5 分钟 TTL 缓存, 避免触发 60 req/h 限流.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.services.app_version_resolver import get_app_version_resolver

router = APIRouter(tags=["version"])


class AppVersionResponse(BaseModel):
    latest_version: str
    min_supported_version: str
    apk_url: str
    release_notes: str
    force_update: bool
    source: str  # "env" | "github" | "default", 方便前端展示"检测方式"


@router.get("/app/version", response_model=AppVersionResponse)
async def app_version() -> AppVersionResponse:
    """Return the latest available APK version and download URL."""
    resolved = await get_app_version_resolver().resolve()
    min_supported = settings.app_min_supported_version.strip() or resolved.latest_version
    return AppVersionResponse(
        latest_version=resolved.latest_version,
        min_supported_version=min_supported,
        apk_url=resolved.apk_url,
        release_notes=resolved.release_notes,
        force_update=bool(settings.app_min_supported_version.strip()),
        source=resolved.source,
    )

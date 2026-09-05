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


#: env 未配置「最低支持版本」时回发的哨兵: 任何版本都 >= 它, 即**没有**版本被判为
#: 不支持。为什么不能用 latest_version 当默认 (P8 修复, 曾经的强更 bug):
#: 存量 v1.4.0 客户端 (fc05d64 起) 的判断是「current < min_supported → 每次启动
#: 必弹, 且跳过/忽略该版本的偏好被无视」。默认若等于 latest, 所有旧包都会落进
#: 「不支持」分支 —— 弹窗虽然还能关掉, 但「稍后再说」失效, 与计划 §九.5
#: 「OTA 对 1.4.0 正常提示且不强制」矛盾。显式配置 APP_MIN_SUPPORTED_VERSION
#: 才会进入不可跳过分支 (此时 force_update 也为 True, 语义一致)。
_NO_MIN_SUPPORTED = "0.0.0"


@router.get("/app/version", response_model=AppVersionResponse)
async def app_version() -> AppVersionResponse:
    """Return the latest available APK version and download URL.

    ``min_supported_version`` / ``force_update`` 只在运维显式配置
    ``APP_MIN_SUPPORTED_VERSION`` 时收紧; 未配置 = 「都能用, 更新可跳过」。
    """
    resolved = await get_app_version_resolver().resolve()
    explicit_min = settings.app_min_supported_version.strip()
    min_supported = explicit_min or _NO_MIN_SUPPORTED
    return AppVersionResponse(
        latest_version=resolved.latest_version,
        min_supported_version=min_supported,
        apk_url=resolved.apk_url,
        release_notes=resolved.release_notes,
        force_update=bool(explicit_min),
        source=resolved.source,
    )

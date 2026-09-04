"""LLM 模型目录端点.

客户端 (Android) 启动时拉取 ``GET /api/v1/llm/models`` 获取可选模型清单,
用于设置页的「对话模型」下拉框. 始终返回静态目录 (代码内置的百炼模型),
并且在 ``llm_allowed_models`` 配置了白名单时按白名单过滤.

注意: 目录里出现的 id **不等于**可用 —— ``default_model`` 是服务端默认
(白名单只约束客户端可选范围, 不约束服务端自己用哪个模型).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.llm_provider import (
    ModelInfo,
    get_model_catalog,
    resolve_server_default_model,
)

router = APIRouter(tags=["llm"])


class LlmModelDto(BaseModel):
    id: str
    display_name: str
    provider: str
    description: str = ""


class LlmModelsResponse(BaseModel):
    models: list[LlmModelDto]
    default_model: str = Field(description="客户端未选时使用的 model_id")


def _filter_catalog(catalog: list[ModelInfo]) -> list[ModelInfo]:
    """Apply optional operator-supplied allow-list to the catalog."""
    from app.config import settings

    raw = settings.llm_allowed_models.strip()
    if not raw:
        return catalog
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    if not allowed:
        return catalog
    return [info for info in catalog if info.id in allowed]


@router.get("/llm/models", response_model=LlmModelsResponse)
async def list_llm_models() -> LlmModelsResponse:
    """Return the static catalog of LLM models available for free dialogue.

    The list is curated server-side so the client never has to hard-code
    model ids. New models are added by updating ``llm_provider._DEFAULT_BAILIAN_MODELS``
    (or by setting ``LLM_EXTRA_MODELS_JSON``).
    """
    catalog = _filter_catalog(get_model_catalog())
    return LlmModelsResponse(
        models=[
            LlmModelDto(
                id=info.id,
                display_name=info.display_name,
                provider=info.provider,
                description=info.description,
            )
            for info in catalog
        ],
        # P3: 默认模型收口到 ``resolve_server_default_model`` (settings 驱动 +
        # 确定性回退); 旧式 ``or catalog[0].id`` 在白名单过滤成空列表时会 IndexError.
        default_model=resolve_server_default_model(),
    )

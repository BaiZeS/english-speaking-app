"""``POST /translate`` (v3.0, 方案 S2.7): 长按没有现成双语的那条消息时调这里.

独立请求、独立预算 (``TRANSLATE_BUDGET_S`` 6.0s), 不占台词那条已经顶格的 25s。
失败一律 503 + 中文可读文案 —— 不机翻占位、不把原文当译文回显。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.services import translate as service
from app.services.drill_grader import LlmUnavailableError

router = APIRouter(tags=["translate"])


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=service.MAX_CHARS)
    #: "zh" = 翻成中文, "en" = 翻成英文。
    target_lang: str = Field(pattern="^(zh|en)$")


class TranslateResponse(BaseModel):
    translated: str
    #: 恒为 ``llm`` —— 翻不出来是 503, 没有"降级翻译"这一档 (D5)。
    source: str = "llm"


@router.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest) -> TranslateResponse:
    text = req.text.strip()
    if not text:
        raise AppError(status_code=422, message="text must not be blank", code="BAD_REQUEST")
    try:
        translated = await service.translate_text(text, req.target_lang)
    except LlmUnavailableError as exc:
        raise AppError(
            status_code=503,
            message="translation service unavailable",
            code="TRANSLATION_UNAVAILABLE",
        ) from exc
    return TranslateResponse(translated=translated)

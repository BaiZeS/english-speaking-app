"""独立语法润色端点 (计划 §5.7, 阶段 P3).

``POST /api/v1/polish`` `{text, model_id?, device_id?, user_id?, collect?}` ——
复盘页/详情页对**任意一句**英文补一次「原句 vs 更好说法」对照。

口径:

* **一次 LLM 调用** (复用 drill 的 `_judge` 容错解析 + 校验错误回喂重试一次模式),
  输出 ``{polished, explanation_cn}``; 模型认为没有可改之处 -> ``polish: null``
  (诚实的"没问题", 不是失败); LLM 不可用 -> 同样 ``polish: null`` +
  ``source="stub"|"heuristic"`` + ``message_cn`` 说明, **绝不编造占位句子** ——
  规则改写容易改错意思, 占位润色比没有润色更有害。
* 润色是**纯文本工具** (不进画像、不出分数), 所以允许客户端 ``model_id``
  (沿用自由对话的选择约定, 但必须落在服务端白名单内 —— 见
  ``llm_provider.resolve_roleplay_model``)。
* ``collect=true`` + 带身份 + 真的产出了对照 -> 自动收藏进个人表达库
  (``source_label="polish"``, 去重走 (user_id, normalized) 唯一索引)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.services import mission_engine, users
from app.services.llm_provider import resolve_roleplay_model
from app.services.mission_engine import Polish

router = APIRouter(tags=["polish"])


class PolishRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    #: 仅**文本用途**的模型覆盖 (白名单内); 留空 = 服务端默认.
    model_id: str | None = Field(default=None, max_length=128)
    #: collect 时需要身份 (没有身份就只润色, 收藏静默跳过并回 note).
    device_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=36)
    #: 润色结果直接收进表达库 (§5.7「可收藏进个人表达库复用」).
    collect: bool = False
    scene_id: str = Field(default="", max_length=64)


class PolishResponse(BaseModel):
    #: 「原句 vs 更好说法」对照; NULL/无问题/LLM 不可用时为 null.
    polish: Polish | None = None
    #: llm | stub | heuristic (来源标记, UI 据此提示是否真实润色).
    source: str
    #: 润色 LLM provenance: 模型 id | "stub".
    llm_source: str | None = None
    #: ``collect`` 成功后返回 expression id; 否则 null.
    expression_id: str | None = None
    #: 给 UI 的说明 (没配 LLM / 已收藏去重等场景); 正常润色时为空.
    note_cn: str = ""


@router.post("/polish", response_model=PolishResponse)
async def polish(req: PolishRequest, db: AsyncSession = Depends(get_db)) -> PolishResponse:
    """独立润色 (§5.7)."""
    text = req.text.strip()
    if not text:
        raise AppError(400, "text is required", "POLISH_TEXT_REQUIRED")
    model = resolve_roleplay_model(req.model_id)
    polish_result, source, llm_source = await mission_engine.polish_text(text, model=model)
    if polish_result is None:
        note = (
            "LLM 未配置或输出不可用, 本次未做润色。"
            if source in ("stub", "heuristic")
            else "这句没有值得改的语法/用词问题, 保持原样即可。"
        )
        return PolishResponse(polish=None, source=source, llm_source=llm_source, note_cn=note)
    expression_id: str | None = None
    note = ""
    if req.collect:
        user = await users.lookup_user(
            db, device_id=req.device_id, user_id=req.user_id, create=bool(req.device_id)
        )
        if user is None:
            if req.user_id:
                # 明确给了 user_id 却查不到 = 调用方写错, 不能装作"没给身份"
                raise AppError(404, f"unknown user_id: {req.user_id}", "USER_NOT_FOUND")
            note = "未给身份 (device_id/user_id), 本次未收藏。"
        else:
            expression_id = await _collect_expression(db, user.id, polish_result, req.scene_id)
            if expression_id:
                note = "已收藏进个人表达库。"
    return PolishResponse(
        polish=polish_result,
        source=source,
        llm_source=llm_source,
        expression_id=expression_id,
        note_cn=note,
    )


async def _collect_expression(
    db: AsyncSession, user_id: str, polish: Polish, scene_id: str
) -> str | None:
    """收藏到表达库 (复用 expressions 的去重 upsert); 返回 id, 失败返回 None."""
    from app.api.v1 import expressions  # 局部 import: routers 之间零环依赖

    row, created = await expressions.upsert_expression(
        db,
        user_id=user_id,
        polished=polish.polished,
        original=polish.original,
        explanation_cn=polish.explanation_cn,
        source_label="polish",
        scene_id=scene_id,
    )
    if created:  # 去重命中时无新行, 不必提交
        await db.commit()
    return str(row.id)


__all__ = ["PolishRequest", "PolishResponse", "polish"]

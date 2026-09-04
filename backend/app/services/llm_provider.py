"""LLM provider abstraction and Bailian (阿里云百炼) OpenAI-compatible client.

自由对话场景需要按场景生成开场白和对话回合.
后端配置 LLM 凭据 (Bailian OpenAI 兼容端点), 应用启动时从
``GET /api/v1/llm/models`` 拉取可用模型列表, 用户在设置页选择
具体 ``model_id``, 自由对话请求中携带该 id 透传到本服务.

未配置 LLM 凭据时, 自动回退到 ``DialogueService`` 中的本地
deterministic fallback, 与改动前的行为兼容.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger
from openai import AsyncOpenAI

from app.config import settings


@dataclass(frozen=True)
class LlmMessage:
    """Role/content pair consumed by chat completions."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LlmCompletion:
    """Single completion result from an LLM provider."""

    content: str
    model: str


class LlmProvider(Protocol):
    """Common surface every LLM backend must expose."""

    async def list_models(self) -> list[str]: ...

    async def chat(
        self,
        *,
        model: str,
        messages: Iterable[LlmMessage],
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: float = 30.0,
    ) -> LlmCompletion: ...


@dataclass(frozen=True)
class ModelInfo:
    """Public-facing model metadata exposed to the Android client.

    ``provider`` lets the UI render a badge; ``description`` is a
    short Chinese hint that helps non-technical users choose.
    """

    id: str
    display_name: str
    provider: str
    description: str


# Hard-coded catalog of Bailian-hosted models we support. The
# ``LLM_DEFAULT_MODEL`` is the one used when the client omits model_id.
_DEFAULT_BAILIAN_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        id="qwen-plus",
        display_name="Qwen Plus",
        provider="bailian",
        description="通义千问 Plus，平衡性能与成本，适合日常对话。",  # noqa: RUF001 (intentional Chinese punctuation)
    ),
    ModelInfo(
        id="qwen-turbo",
        display_name="Qwen Turbo",
        provider="bailian",
        description="通义千问 Turbo，速度快、价格低，适合轻量场景。",  # noqa: RUF001 (intentional Chinese punctuation)
    ),
    ModelInfo(
        id="qwen-max",
        display_name="Qwen Max",
        provider="bailian",
        description="通义千问 Max，能力最强，适合复杂表达。",  # noqa: RUF001 (intentional Chinese punctuation)
    ),
    ModelInfo(
        id="deepseek-v3",
        display_name="DeepSeek V3",
        provider="bailian",
        description="DeepSeek V3，英文表达自然，适合口语陪练。",  # noqa: RUF001 (intentional Chinese punctuation)
    ),
)


def _parse_model_catalog() -> list[ModelInfo]:
    """Merge hard-coded defaults with any operator-supplied overrides.

    Operators can append extra ``ModelInfo`` rows by setting
    ``LLM_EXTRA_MODELS_JSON`` to a JSON array of ``{"id","display_name",
    "provider","description"}`` objects. Useful for private deployments
    that proxy Bailian through their own gateway.
    """
    catalog: list[ModelInfo] = list(_DEFAULT_BAILIAN_MODELS)
    raw = settings.llm_extra_models_json.strip()
    if not raw:
        return catalog
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("LLM_EXTRA_MODELS_JSON invalid; ignoring. err={}", exc)
        return catalog
    if not isinstance(payload, list):
        logger.warning("LLM_EXTRA_MODELS_JSON must be a JSON array; ignoring.")
        return catalog
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            catalog.append(
                ModelInfo(
                    id=str(item["id"]),
                    display_name=str(item.get("display_name", item["id"])),
                    provider=str(item.get("provider", "custom")),
                    description=str(item.get("description", "")),
                )
            )
        except KeyError:
            logger.warning("LLM_EXTRA_MODELS_JSON entry missing 'id'; skipping: {}", item)
    return catalog


# ---------- Model resolution (single source of truth for the fallback chain) ----------
#
# 已知缺陷修正 (T2 发现, T4 落地): 旧链在 ``LLM_ALLOWED_MODELS`` /
# ``LLM_DEFAULT_MODEL`` 都没配时会返回**硬编码的 qwen-plus** (而且走的是
# ``next(iter(set))``, 顺序都不确定)。qwen-plus 这类模型随时可能配额耗尽
# (2026-08-31 实测本机百炼 qwen-plus/max/turbo 全 403), "藏一个具体模型 id 在代码里"
# 的兜底本质上会烂掉. 现在的链条全部由运维配置驱动、且确定性排序:
#
#   服务端默认 (判分/生成一律用它):  settings.LLM_DEFAULT_MODEL
#                                     -> 首个 ALLOWED 条目
#                                     -> 内置目录第一项 (顺序固定, 仅剩的确定性信号)
#   角色对话文本 (可按老约定跟随客户端):  白名单 (显式 ALLOWED, 未配时 = 内置目录)
#                                     命中 client model_id -> 用它
#                                     否则回落服务端默认
#
# **判分永远不开放客户端选模型** (T3 先例: 同一门课不同题用不同模型, 分数没法
# 比较, 也没法拿去更新画像)。这条链只提供两个入口: ``resolve_server_default_model``
# (判分/生成) 与 ``resolve_roleplay_model`` (人设回复/润色文本)。


def explicit_allowed_models() -> list[str]:
    """Operator allow-list from ``LLM_ALLOWED_MODELS`` (empty when unset)."""
    return [item.strip() for item in settings.llm_allowed_models.split(",") if item.strip()]


def allowed_model_ids() -> list[str]:
    """The list that gates client ``model_id``: explicit allow-list, else catalog.

    Order is stable here on purpose — the fallback ("first allowed entry") must
    be deterministic across restarts (the old code did ``next(iter(set))``).
    """
    explicit = explicit_allowed_models()
    if explicit:
        return explicit
    return [info.id for info in get_model_catalog()]


def resolve_server_default_model() -> str:
    """Server-side default (grading / generation / mission turns).

    Chain: ``LLM_DEFAULT_MODEL`` -> first allow-list entry -> first catalog entry.
    No hard-coded dead model id anywhere.
    """
    default = settings.llm_default_model.strip()
    if default:
        return default
    allowed = allowed_model_ids()
    if allowed:
        first = allowed[0]
        logger.warning(
            "LLM_DEFAULT_MODEL unset; falling back to the first allowed/catalog model {}",
            first,
        )
        return first
    logger.error("LLM model catalog is empty — configuration bug")
    return ""


def resolve_roleplay_model(model_id: str | None) -> str:
    """Resolve a caller-supplied ``model_id`` for *text* (persona reply / polish).

    Honored only when inside the allow-list (back-compat: with no allow-list the
    built-in catalog is the allow-list, mirroring the pre-v2.0 contract). Grades
    must never be resolved through this function — see
    :func:`resolve_server_default_model`.
    """
    requested = (model_id or "").strip()
    if not requested:
        return resolve_server_default_model()
    if requested in allowed_model_ids():
        return requested
    logger.warning("model_id {!r} is not in the server allow-list; using default", requested)
    return resolve_server_default_model()


# ---------- Bailian (OpenAI-compatible) ----------


class BailianOpenAIProvider:
    """OpenAI-compatible client targeting the Bailian Maas endpoint.

    The Maas gateway exposes ``/compatible-mode/v1/chat/completions`` with the
    standard OpenAI Chat Completions schema, so we use the official
    ``openai.AsyncOpenAI`` SDK and only swap ``base_url`` + ``api_key``.
    """

    def __init__(self) -> None:
        self._base_url = settings.llm_base_url.rstrip("/")
        self._api_key = settings.llm_api_key
        self._client: AsyncOpenAI | None = None
        if self._api_key:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=30.0,
                max_retries=2,
            )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    @property
    def default_model(self) -> str:
        """Server default via the config-driven chain (never a hard-coded model id)."""
        return resolve_server_default_model()

    async def list_models(self) -> list[str]:
        """Best-effort model list from the upstream Maas gateway.

        If the upstream doesn't support ``/models`` (some Bailian
        deployments do not), we fall back to the static catalog so the
        Android UI still has something to render.
        """
        if not self.is_configured or self._client is None:
            return [info.id for info in _DEFAULT_BAILIAN_MODELS]
        try:
            response = await self._client.models.list()
        except Exception as exc:
            logger.warning("Bailian /models failed; using static catalog. err={}", exc)
            return [info.id for info in _DEFAULT_BAILIAN_MODELS]
        ids = sorted(
            {item.id for item in getattr(response, "data", []) if getattr(item, "id", None)}
        )
        if not ids:
            return [info.id for info in _DEFAULT_BAILIAN_MODELS]
        curated = {info.id for info in _DEFAULT_BAILIAN_MODELS}
        return sorted(set(ids) | curated)

    async def chat(
        self,
        *,
        model: str,
        messages: Iterable[LlmMessage],
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: float = 30.0,
    ) -> LlmCompletion:
        if self._client is None:
            raise RuntimeError("LLM provider is not configured (missing LLM_API_KEY).")
        payload = [{"role": msg.role, "content": msg.content} for msg in messages]
        response = await self._client.with_options(timeout=timeout).chat.completions.create(
            model=model or self.default_model,
            messages=payload,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = _extract_content(response)
        return LlmCompletion(content=content, model=getattr(response, "model", model))


def _extract_content(response: Any) -> str:
    """Pull the textual content out of an OpenAI ChatCompletion response."""
    try:
        choice = response.choices[0]
    except (IndexError, AttributeError) as exc:
        raise RuntimeError(f"LLM response missing choices: {response!r}") from exc
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if not content:
        raise RuntimeError("LLM response contained empty content.")
    if not isinstance(content, str):
        return str(content).strip()
    return content.strip()


# ---------- Module-level singleton ----------


_provider: LlmProvider | None = None


def get_llm_provider() -> LlmProvider:
    """Return the process-wide LLM provider.

    Keeping it lazy avoids constructing an ``AsyncOpenAI`` client (and
    touching network DNS) at import time, which would otherwise break
    unit tests that never call ``/dialogue/*``.
    """
    global _provider
    if _provider is None:
        _provider = BailianOpenAIProvider()
    return _provider


def get_model_catalog() -> list[ModelInfo]:
    """Static catalog exposed to clients regardless of upstream availability."""
    return _parse_model_catalog()


def reset_llm_provider_for_tests() -> None:
    """Drop the cached provider. Only used by tests that mutate settings."""
    global _provider
    _provider = None

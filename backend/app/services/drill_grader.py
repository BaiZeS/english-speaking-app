"""打基础 4 种题型的 drill 评分引擎 (计划 §5.4 / §5.5).

题型 -> 评分来源 (§5.4 的表原样落地):

============  ==============================  ===============================
题型           评分方式                         数据来源
============  ==============================  ===============================
``read_along`` 复用 ``/score`` 的 ISE 管线      讯飞 ISE (exact_reference)
``retell``     学员英文 vs ``reference_answer`` LLM 判分 (1 次/题)
``translate``  学员英文 vs 参考英文译文         LLM 判分 (1 次/题)
``make_sentence`` 目标词用法 + 语境自然度       LLM 判分 (accept_notes 当 rubric)
============  ==============================  ===============================

内容契约 (T2 交付, 不可破坏)
----------------------------
``translate`` 题的**中文原句在 ``step.ref_text``**, 参考英文答案在
``step.reference_answer``. 于是:

* 中文**永远不进 ISE** —— 本模块只有 ``read_along`` 会碰 ISE, 且送的是英文 ``ref_text``;
* 翻译判分把中文当**题目**喂给 LLM, 学员英文与参考英文才是答案的两侧.

无凭据时必须照样能玩 (本机讯飞没 key, CI 一律空凭据)
----------------------------------------------------
* ``read_along``: :class:`app.services.xunfei_asr.XunfeiASRProvider` 自己回退
  StubASR, 分数标 ``source="stub"`` (恒 95 分, 是否可信交给 UI 按 source 警示);
* LLM 三类: 未配置 / 调用异常 / 输出两次都不合规 -> 退回**确定性启发式**
  (参考要点词干覆盖率 + 长度带), ``source="heuristic"``, ``llm_source="stub"``,
  ``feedback_cn`` 以「LLM 未配置」或「LLM 判分失败」开头.
  一个 drill 不会因为外部服务缺失而 500, 也不会静默冒充真实判分.

LLM 调用预算: 每题恰好 1 次调用; JSON 不合规时把校验错误回喂再试 1 次 (§5.5),
没有第三次 —— 直接降级, 移动端不等第二分钟.

P3 接缝: :func:`ability_evidence` 把一次评分算成 §5.6 的维度证据 (含 stub 门控权重);
P3 (T4) 起由 ``course_sessions`` 在每次评分后把该列表交给
:func:`app.services.ability_engine.record_step_evidence` 落库 (事件流水 + EWMA 画像)。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal, Protocol, TypeVar, cast

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.core.errors import AppError
from app.models.course import FoundationStep, StepType
from app.models.schema import WordScore
from app.scoring.read_along import score_read_along
from app.services.audio_input import speech_rate_from_recognition
from app.services.interfaces import ASRProvider
from app.services.llm_provider import LlmMessage, get_llm_provider
from app.services.xunfei_asr import XunfeiASRProvider
from app.services.xunfei_iat import XunfeiIatProvider

# ====== 常量 ======

#: 达标线: 沿用跟读模式既有的 60 分过关口径 (§5.4 passed(>=60)).
PASS_SCORE = 60.0

#: ISE 参考文本长度上限, 与 ``ScoreRequest.ref_text`` 同源 (T2 契约: /score 2000 字).
ISE_REF_MAX_CHARS = 2000

#: 单次判分调用的超时与输出预算 (移动端延迟预算, 计划 §四).
LLM_TIMEOUT_S = 20.0
LLM_MAX_TOKENS = 400

#: 文本型 drill 答案的取材上限 (手敲英文或 IAT 转写).
ANSWER_MAX_CHARS = 2000

IseRefMode = Literal["exact_reference", "transcript_anchored"]

#: 文本题型 (read_along 之外), 判分流程同一套, 只是 rubric 不同.
TextStepKind = Literal["retell", "translate", "make_sentence"]

#: 能力画像四维 (§5.6), 也是 ``AbilityEvidence.dimension`` 的取值域.
Dimension = Literal["pronunciation", "grammar", "vocabulary", "fluency"]

#: ``DrillGrade.source`` -- 分数是谁给的:
#:   xunfei=真实 ISE | stub=占位 ISE | llm=真实判分 | heuristic=确定性降级.
GradeSource = Literal["xunfei", "stub", "llm", "heuristic"]

#: ``practice_steps.source`` 里"这一步没有评分证据"的取值 (人工跳过).
SKIP_SOURCE = "skip"

_STUB_LLM = "stub"
_STUB_SOURCES = frozenset({"stub", "heuristic"})

#: 生产 provider 单例: ISE 走 XunfeiASRProvider (缺凭据自己回 StubASR).
#: 测试可以放心换掉这两个模块属性, 不必再往函数签名里塞参数.
_ISE: ASRProvider = XunfeiASRProvider()

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']*")

#: 功能词: 覆盖率只算内容词, 免得 ``the a of`` 撑出假高分.
_STOPWORDS = frozenset(
    {
        "a",
        "all",
        "an",
        "and",
        "any",
        "are",
        "at",
        "be",
        "because",
        "but",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "get",
        "had",
        "has",
        "have",
        "he",
        "her",
        "him",
        "his",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "just",
        "like",
        "me",
        "more",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "please",
        "she",
        "so",
        "some",
        "t",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "thing",
        "think",
        "this",
        "to",
        "too",
        "up",
        "us",
        "was",
        "we",
        "well",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


# ====== 返回契约 ======


class DrillMistake(BaseModel):
    """翻译题的一条误译/漏译对照 (复盘页「原话 vs 更好说法」的原料)."""

    #: 对应的中文原文片段 (题目侧, 只给人看, 绝不进 ISE).
    source_cn: str = Field(default="", max_length=300)
    #: 学员说的英文 (空 = 漏译).
    said: str = Field(default="", max_length=500)
    #: 更好的英文说法 (能直接开口用的).
    better: str = Field(default="", max_length=500)
    explanation_cn: str = Field(default="", max_length=300)


class DrillGrade(BaseModel):
    """一次 drill 尝试的评分结果 (§5.4 ``DrillGrade``).

    维度分**可空**: ``None`` = 本题型在该维度上没有证据, 与 0 分是两回事 (§5.6 画像
    门控的前提). 整份结果既落 ``practice_steps`` 一行, 也写进会话 doc 快照.
    """

    step_id: str
    step_type: StepType
    score: float = Field(ge=0, le=100)
    passed: bool
    #: 达标线回给客户端渲染「>=60 过关」, 不在 UI 里硬编码.
    pass_score: float = PASS_SCORE
    feedback_cn: str = Field(default="", max_length=500)

    pronunciation: float | None = Field(default=None, ge=0, le=100)
    fluency: float | None = Field(default=None, ge=0, le=100)
    completeness: float | None = Field(default=None, ge=0, le=100)
    grammar: float | None = Field(default=None, ge=0, le=100)
    vocabulary: float | None = Field(default=None, ge=0, le=100)

    #: ISE 认出的文本 / IAT 转写 / 学员敲的英文 (落 ``practice_steps.transcript``).
    transcript: str | None = None
    #: 逐词染色 (只有跟读有).
    word_details: list[WordScore] = Field(default_factory=list)
    #: 复述题命中的参考要点.
    key_points_hit: list[str] = Field(default_factory=list)
    #: 翻译题的误译/漏译清单.
    mistakes: list[DrillMistake] = Field(default_factory=list)
    speech_rate_wpm: float | None = None
    ise_ref_mode: IseRefMode | None = None
    source: GradeSource = "stub"
    #: 判分 LLM 的 provenance: 模型 id | ``stub`` (未配置或降级) | ``None`` (没用 LLM).
    llm_source: str | None = None


class AbilityEvidence(BaseModel):
    """一次评分对某个能力维度的证据 (§5.6 ``ability_events`` 的形状).

    P2 **只算不写**. ``weight=0`` 是门控契约: 占位证据 (stub / 启发式) 不许拉动画像
    —— 本机讯飞没 key 时恒 95 分, 不门控会把画像一路推高 (§四 决策表).
    """

    dimension: Dimension
    score: float = Field(ge=0, le=100)
    source: str
    weight: float = Field(ge=0, le=1)
    #: 发音维度的参考口径; 其它维度为 None.
    ise_ref_mode: IseRefMode | None = None


_J = TypeVar("_J", bound=BaseModel)


class LlmUnavailableError(Exception):
    """LLM 判分不可用 (未配置 / 调用失败 / 重试一次后输出仍不合规)."""

    def __init__(self, reason: str, *, not_configured: bool = False) -> None:
        super().__init__(reason)
        self.not_configured = not_configured

    @property
    def label(self) -> str:
        """降级反馈的前缀 —— 诚实告诉学员这是占位分."""
        return "LLM 未配置:" if self.not_configured else "LLM 判分失败:"


# ====== 1) read_along: 复用 /score 的 ISE 管线 ======


async def grade_read_along(
    step: FoundationStep,
    audio_bytes: bytes,
    *,
    asr: ASRProvider | None = None,
) -> DrillGrade:
    """跟读题: 讯飞 ISE -> ``AsrResult`` -> :func:`app.scoring.read_along` 聚合.

    ``asr`` 走 :class:`app.services.interfaces.ASRProvider` Protocol (测试可注入假
    provider); 默认生产 provider, 缺凭据时它自己回 StubASR 并标 ``source="stub"``.
    """
    provider = asr or _ISE
    ref_text = (step.ref_text or "").strip()
    if not ref_text:
        raise AppError(400, f"read_along step {step.id} has no ref_text", "STEP_CONTENT_INVALID")
    if len(ref_text) > ISE_REF_MAX_CHARS:
        raise AppError(400, "read_along ref_text exceeds ISE limit", "REF_TEXT_TOO_LONG")
    if not audio_bytes:
        raise AppError(400, "audio_b64 is required for a read_along step", "AUDIO_REQUIRED")

    result = await provider.recognize(audio_bytes, ref_text, category="read_sentence")
    wpm = speech_rate_from_recognition(result.recognized, audio_bytes)
    scored = score_read_along(ref_text=ref_text, asr=result, speech_rate_wpm=wpm, pause_count=0)
    return DrillGrade(
        step_id=step.id,
        step_type="read_along",
        score=scored.total,
        passed=scored.total >= PASS_SCORE,
        feedback_cn=scored.suggestion or "发音和节奏都稳, 保持这个语速。",
        pronunciation=scored.pronunciation,
        fluency=scored.fluency,
        completeness=scored.completeness,
        transcript=result.recognized,
        word_details=scored.word_details,
        speech_rate_wpm=round(wpm, 1),
        # 跟读有标准答案 -> 标准口径; transcript_anchored 留给 P3 的自由产出.
        ise_ref_mode="exact_reference",
        source="xunfei" if result.source == "xunfei" else "stub",
        llm_source=None,
    )


# ====== 2) LLM 判分: schema + prompt + 容错解析 + 重试 ======


class _Judgement(BaseModel):
    """三种判分 schema 的公共部分 (分数 + 中文点评), 让调用方能直接读这两个字段."""

    score: float = Field(ge=0, le=100)
    feedback_cn: str = Field(default="", max_length=500)


class _RetellJudgement(_Judgement):
    key_points_hit: list[str] = Field(default_factory=list, max_length=12)


class _TranslateJudgement(_Judgement):
    mistakes: list[DrillMistake] = Field(default_factory=list, max_length=6)


class _SentenceJudgement(_Judgement):
    used_target_word: bool = True


_SCHEMAS: dict[TextStepKind, type[_Judgement]] = {
    "retell": _RetellJudgement,
    "translate": _TranslateJudgement,
    "make_sentence": _SentenceJudgement,
}

_SYSTEM_BASE = (
    "你是英语口语教学的判分器, 学员是中文母语的企业管理者: 能读写、开口少. "
    "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏. "
    "分数必须有区分度: 说对要点且基本可听懂才及格 (>=60), 只沾到边或答非所问不及格; "
    "满分留给几乎没有表达问题的回答. "
    "feedback_cn 为 1-2 句简体中文, 先结论后细节, 说清下一句该怎么改, 不写「很棒」这类空话."
)

_ANSWER_RULE = (
    "只按**学员的英文作答**判分: 不要把中文题干当答案, 也不要求逐字复述参考答案 "
    "(口语允许换说法), 但语法和用词错误必须体现在分数里."
)

_JSON_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*|\s*```\s*$")


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _parse_llm_json(text: str) -> dict[str, Any]:
    """容错解析 LLM 该返回的 JSON 对象 (§5.5 统一模式).

    先剥 markdown 围栏; ``json.loads`` 失败再退一步取第一个 ``{`` 到最后一个 ``}``
    的切片 —— 模型总爱在 JSON 前后加解说句. 拿不到对象才抛, 交给 :func:`_judge` 做
    "错误回喂重试一次".
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = _JSON_FENCE_RE.sub("", candidate).strip()
    data: Any
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("输出里找不到 JSON 对象") from None
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("输出不是 JSON 对象")
    return cast("dict[str, Any]", data)


def _resolve_judge_model() -> str:
    """判分用的模型 id, 跟随 ``LLM_DEFAULT_MODEL`` (本机已切 qwen3.8-max).

    drill 判分**不让客户端选模型**: 判分口径必须在一门课内稳定, 否则同课不同步的
    分数没法比较, 也没法拿去更新画像.
    """
    provider = get_llm_provider()
    return cast(str, getattr(provider, "default_model", "") or "") or "llm"


async def _judge(
    schema: type[_J],
    messages: Sequence[LlmMessage],
    *,
    max_tokens: int = LLM_MAX_TOKENS,
    model: str | None = None,
) -> _J:
    """一次 LLM 判分 + 容错解析; 输出不合规则**回喂校验错误重试 1 次**.

    未配置 -> ``LlmUnavailableError(not_configured=True)``; 传输异常 / 二次仍不合规
    -> ``LlmUnavailableError``. 调用方一律降级到确定性启发式.

    P3 起该模式被 mission/polish/dialogue 复用 (见 ``app.services.mission_engine``):
    ``max_tokens`` 给更大的综合 JSON 留预算; ``model`` **只允许纯文本用途**
    (润色) 传入覆盖 —— 判分/任务判定恒用服务端默认模型 (``_resolve_judge_model``),
    调用方不许拿客户端选的模型污染分数。
    """
    provider = get_llm_provider()
    if not cast(bool, getattr(provider, "is_configured", False)):
        raise LlmUnavailableError("LLM 未配置 (缺 LLM_API_KEY)", not_configured=True)
    resolved_model = model or _resolve_judge_model()

    async def _ask(turns: Sequence[LlmMessage]) -> str:
        completion = await provider.chat(
            model=resolved_model,
            messages=turns,
            temperature=0.2,
            max_tokens=max_tokens,
            timeout=LLM_TIMEOUT_S,
        )
        return completion.content

    turns = list(messages)
    try:
        raw = await _ask(turns)
    except Exception as exc:  # 网络/超时/provider 未就绪: 不在学员身上重试
        raise LlmUnavailableError(f"LLM 调用失败: {exc}") from exc

    error_text = ""
    try:
        return schema.model_validate(_parse_llm_json(raw))
    except (ValueError, ValidationError) as first_error:
        error_text = _truncate(str(first_error), 300)
        logger.warning("drill judgement malformed, retrying once | err={}", error_text)

    retry_turns = [
        *turns,
        LlmMessage(role="assistant", content=_truncate(raw, 1200)),
        LlmMessage(
            role="user",
            content=(
                f"上一条输出不合格 ({error_text}). "
                "严格按要求的字段名与类型重发, 只输出那个 JSON 对象, 不要任何多余文字."
            ),
        ),
    ]
    try:
        raw2 = await _ask(retry_turns)
        return schema.model_validate(_parse_llm_json(raw2))
    except ValidationError as exc:
        raise LlmUnavailableError(f"重试一次后字段仍不合规: {exc}") from exc
    except Exception as exc:  # JSON 仍坏 / 调用又失败: 到此为止, 降级
        raise LlmUnavailableError(f"重试一次后输出仍不可用: {exc}") from exc


def _judge_prompt(kind: TextStepKind, step: FoundationStep, answer_en: str) -> list[LlmMessage]:
    """三种文本题型的判分 prompt (一次调用要齐 score + 中文点评 + 该题型细节字段)."""
    if kind == "retell":
        user = (
            f"题型: 复述 (学员听完材料后用自己的话说).\n"
            f"听力材料:\n{step.ref_text}\n\n"
            f"参考要点 (标准答案):\n{step.reference_answer}\n\n"
            f"评分要点: {step.accept_notes}\n\n"
            f"学员口述:\n{answer_en}\n\n"
            f"{_ANSWER_RULE}\n"
            "分数口径: 关键信息说全且基本通顺 80-100; 说到大部分要点但有明显缺漏或语法问题"
            " 60-79; 只沾到边或答非所问 <60.\n"
            '只输出 JSON: {"score": 0-100, "feedback_cn": "中文点评",'
            ' "key_points_hit": ["命中的参考要点词组"]}'
        )
    elif kind == "translate":
        must = f"本题要求用到词 {step.target_word}. " if step.target_word else ""
        user = (
            f"题型: 中译英 (把中文说成英文).\n"
            f"中文原句 (题目, 不是答案): {step.ref_text or step.cn_prompt}\n"
            f"参考译文: {step.reference_answer}\n"
            f"{must}评分要点: {step.accept_notes}\n\n"
            f"学员英文:\n{answer_en}\n\n"
            "mistakes 只在确有语法/用词/漏译时给出 (最多 3 条, 按重要程度排); "
            "说得自然地道就给空数组. said 用学员原话, better 给能直接开口的说法, "
            "explanation_cn 一句话.\n"
            "分数口径: 意思到位且说得出口 80-100; 能听懂但有错误 60-79; "
            "意思错或漏关键信息 <60.\n"
            '只输出 JSON: {"score": 0-100, "feedback_cn": "中文点评", "mistakes": '
            '[{"source_cn": "中文片段", "said": "学员英文", "better": "更好的英文", '
            '"explanation_cn": "一句话解释"}]}'
        )
    else:
        user = (
            f"题型: 造句.\n"
            f"目标词: {step.target_word}\n"
            f"参考句: {step.reference_answer}\n"
            f"评分要点 (必须满足): {step.accept_notes}\n\n"
            f"学员英文:\n{answer_en}\n\n"
            "判两件事: 目标词**用法是否正确** (词性/搭配/语义都对, 只把词塞进句子里不算), "
            "以及整句在该场景里是否自然可用; used_target_word 是前一件的判断结果.\n"
            "分数口径: 用法对且自然 80-100; 用法对但句子生硬 60-79; "
            "没用目标词或用法错 <60.\n"
            '只输出 JSON: {"score": 0-100, "feedback_cn": "中文点评",'
            ' "used_target_word": true|false}'
        )
    return [
        LlmMessage(role="system", content=_SYSTEM_BASE),
        LlmMessage(role="user", content=user),
    ]


# ====== 3) 确定性启发式降级 ======


def _answer_tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _content_tokens(text: str) -> set[str]:
    return {t for t in _answer_tokens(text) if t not in _STOPWORDS}


def _stem(token: str) -> str:
    """剥常见屈折尾, 让 ``ordering`` 能命中参考里的 ``order``.

    参考侧与作答侧过同一个函数, 所以只要归一化**一致**就行; 剩下的边角
    (``boxes`` -> ``boxe``) 由 :func:`_same_stem` 的有界前缀匹配兜住.
    """
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _same_stem(left: str, right: str) -> bool:
    """词干是否算同一个词: 相等, 或多出的部分 <=3 个字母 (仅前缀归一化的残余).

    只对 3 字母以上的词干放前缀匹配 —— 否则参考里的 ``us`` 会命中 ``usage``,
    降级分就变成白送了.
    """
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= 3 and longer.startswith(shorter) and len(longer) - len(shorter) <= 3


def _matched_terms(answer: str, reference: str) -> tuple[float, list[str]]:
    """``(参考要点覆盖率, 命中的词干)`` —— 分子分母都来自参考答案本身."""
    ref_terms = {_stem(t) for t in _content_tokens(reference)}
    answer_stems = {_stem(t) for t in _answer_tokens(answer)}
    if not ref_terms or not answer_stems:
        return 0.0, []
    hits = sorted(term for term in ref_terms if any(_same_stem(tok, term) for tok in answer_stems))
    return len(hits) / len(ref_terms), hits


def _overlap_score(answer_en: str, reference: str) -> tuple[float, list[str]]:
    """覆盖率定主分 (全覆盖 = 100), 长度带做惩罚 (太短没内容 / 太长灌水).

    纯函数、无随机数 —— 降级分也必须可复现, CI 才能直接断言分数。
    """
    coverage, hits = _matched_terms(answer_en, reference)
    if not hits:
        return 0.0, []
    score = 100.0 * coverage
    words = len(_answer_tokens(answer_en))
    if words < 3:
        score -= 25.0
    elif words > max(30, 4 * len(hits)):
        score -= 10.0
    return round(max(0.0, min(100.0, score)), 1), hits


def _make_sentence_heuristic(answer_en: str, target_word: str) -> float:
    """造句降级分: 出现目标词给 70 起 (刚过线), 说得越多越给到 100; 没出现 -> 30."""
    target = _stem(target_word.strip().lower())
    tokens = _answer_tokens(answer_en)
    stems = {_stem(t) for t in tokens}
    if not target or not any(_same_stem(stem, target) for stem in stems):
        return 30.0
    return round(min(100.0, 70.0 + max(0.0, (len(tokens) - 4) * 6.0)), 1)


def _score_fallback(step: FoundationStep, answer_en: str, kind: StepType) -> float:
    if kind == "make_sentence":
        return _make_sentence_heuristic(answer_en, step.target_word)
    score, _ = _overlap_score(answer_en, step.reference_answer or step.ref_text)
    return score


def _degraded(
    step: FoundationStep,
    answer_en: str,
    kind: TextStepKind,
    failure: LlmUnavailableError,
) -> DrillGrade:
    """LLM 不可用时的诚实降级: 确定性启发式分 + 前缀标注.

    降级**必须留 WARNING**: 分数口径从"模型语义判分"换成了"词面覆盖率", 线上要能在日志里
    看到是谁在什么时候换了口径, 不然画像与复盘报告会被当成真实评测解读.
    """
    logger.warning(
        "drill grading degraded to heuristic | step={} type={} reason={}", step.id, kind, failure
    )
    score = _score_fallback(step, answer_en, kind)
    hits: list[str] = []
    if kind == "retell":
        _, hits = _overlap_score(answer_en, step.reference_answer or step.ref_text)
    note = (
        "未做语义判分, 分数按参考要点的词面覆盖率与长度估算。"
        if failure.not_configured
        else "模型输出不可用, 分数按参考要点的词面覆盖率与长度估算。"
    )
    return DrillGrade(
        step_id=step.id,
        step_type=kind,
        score=score,
        passed=score >= PASS_SCORE,
        feedback_cn=_truncate(failure.label + note, 500),
        transcript=answer_en,
        key_points_hit=_clean_points(hits),
        source="heuristic",
        llm_source=_STUB_LLM,
        **_dimensions_for(kind, score),
    )


def _clean_points(items: Sequence[str]) -> list[str]:
    return [_truncate(item, 60) for item in items[:12]]


def _dimensions_for(kind: StepType, score: float) -> dict[str, float | None]:
    """每个题型往哪些能力维度记分 (§5.4 表 + §5.6 维度口径).

    复述 = 词汇 (靠内容词命中); 翻译/造句 = 语法 + 词汇. 跟读不走这里 —— 它给的是
    发音/流利/完整三维 (ISE 口径).
    """
    match kind:
        case "retell":
            return {"vocabulary": score}
        case "translate" | "make_sentence":
            return {"grammar": score, "vocabulary": score}
    return {}


# ====== 4) 三个文本题型入口 + 统一分派 ======


async def grade_retell(step: FoundationStep, answer_en: str) -> DrillGrade:
    """复述题判分 (``answer_en`` = 学员口述文本或 IAT 转写)."""
    return await _graded_text_step(step, answer_en, "retell")


async def grade_translate(step: FoundationStep, answer_en: str) -> DrillGrade:
    """翻译题判分 (``answer_en`` = 学员说的英文; 中文题干只进 prompt, 不进 ISE)."""
    return await _graded_text_step(step, answer_en, "translate")


async def grade_make_sentence(step: FoundationStep, answer_en: str) -> DrillGrade:
    """造句题判分 (LLM 按 ``accept_notes`` 判目标词用法与语境自然度)."""
    return await _graded_text_step(step, answer_en, "make_sentence")


async def _graded_text_step(
    step: FoundationStep,
    answer_en: str,
    kind: TextStepKind,
) -> DrillGrade:
    """文本题型公共流程: LLM 判分 -> 失败降级 -> 组装 :class:`DrillGrade`."""
    judgement: _Judgement
    try:
        judgement = await _judge(_SCHEMAS[kind], _judge_prompt(kind, step, answer_en))
    except LlmUnavailableError as exc:
        return _degraded(step, answer_en, kind, exc)
    score = round(judgement.score, 1)
    points = (
        _clean_points(cast("_RetellJudgement", judgement).key_points_hit)
        if kind == "retell"
        else []
    )
    mistakes = list(cast("_TranslateJudgement", judgement).mistakes) if kind == "translate" else []
    used_target = getattr(judgement, "used_target_word", True) is not False
    if kind == "make_sentence" and not points and used_target and step.target_word:
        points = [_truncate(step.target_word, 60)]
    return DrillGrade(
        step_id=step.id,
        step_type=kind,
        score=score,
        passed=score >= PASS_SCORE,
        feedback_cn=_truncate(judgement.feedback_cn, 500) or _fallback_feedback(kind),
        transcript=answer_en,
        key_points_hit=points,
        mistakes=mistakes,
        source="llm",
        llm_source=_resolve_judge_model(),
        **_dimensions_for(kind, score),
    )


def _fallback_feedback(kind: StepType) -> str:
    return {
        "retell": "要点基本说到了, 换成自己的连接词会更顺。",
        "translate": "意思到位, 可以直接开口用。",
        "make_sentence": "目标词用法正确。",
        "read_along": "发音清晰。",
    }[kind]


def resolve_answer_text(step: FoundationStep, text: str, transcript: str | None) -> str:
    """文本型 drill 的答案取材: 手敲优先, 其次音频转写; 都没有 -> 400.

    **不做任何隐式回退** (§四「干掉魔法字符串」同一条纪律): 空答案绝不能拿课程的
    ``ref_text`` / ``reference_answer`` 代打, 那会造出假通过.
    """
    candidate = (text or (transcript or "")).strip()[:ANSWER_MAX_CHARS]
    if candidate:
        return candidate
    raise AppError(
        400,
        f"step {step.id} ({step.type}) needs a text answer or transcribable audio",
        "ANSWER_REQUIRED",
    )


class IatTranscriber(Protocol):
    """讯飞 IAT 的最小面 (便于测试注入; 生产实现是 ``XunfeiIatProvider``)."""

    async def transcribe(self, pcm: bytes) -> str | None: ...


_IAT = XunfeiIatProvider()


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    iat: IatTranscriber | None = None,
) -> str | None:
    """语音作答的英文转写 (讯飞 IAT). 缺凭据或失败 -> ``None``.

    IAT 没有 stub 实现 (与 ISE 不同 —— 转写没有"完美占位"这种东西), 所以空凭据环境下
    复述/翻译/造句的语音输入拿不到转写; 端点必须翻成清楚的 400 而不是静默给占位分:
    **没有转写就没有证据**. 注入 ``iat`` 只是为了让"有转写"这条分支能进测试.
    """
    if not audio_bytes:
        return None
    return await (iat or _IAT).transcribe(audio_bytes)


async def grade_step(
    *,
    step: FoundationStep,
    audio_bytes: bytes = b"",
    answer_text: str = "",
    asr: ASRProvider | None = None,
    iat: IatTranscriber | None = None,
) -> DrillGrade:
    """按题型分派评分 —— 端点只需要调这一个函数.

    取材口径: ``read_along`` 只认音频 (送 ISE, 参考文本是英文原句); 其余题型优先用
    ``answer_text`` (客户端手敲), 只有音频时用 IAT 转写. 转不出来就 400
    ``TRANSCRIPT_UNAVAILABLE`` —— **没有转写就没有证据**, 不拿占位分冒充一次口语作答.
    """
    if step.type == "read_along":
        return await grade_read_along(step, audio_bytes, asr=asr)
    if step.type not in ("retell", "translate", "make_sentence"):
        # 课程是磁盘/DB 来的外部数据, 脏 type 不能变成 500.
        raise AppError(400, f"unsupported step type {step.type!r}", "STEP_TYPE_UNSUPPORTED")
    text = answer_text.strip()
    if not text and audio_bytes:
        transcript = (await transcribe_audio(audio_bytes, iat=iat) or "").strip()
        if not transcript:
            raise AppError(
                400,
                f"step {step.id} ({step.type}): 音频无法转写 (讯飞 IAT 未配置), 请改用 text 作答",
                "TRANSCRIPT_UNAVAILABLE",
            )
        text = transcript
    answer = resolve_answer_text(step, text, None)
    kind: TextStepKind = step.type  # 上面已经收窄过
    return await _graded_text_step(step, answer, kind)


# ====== 5) P3 接缝 ======


def ability_evidence(grade: DrillGrade) -> list[AbilityEvidence]:
    """把一次评分拆成 §5.6 的维度证据 (落库管线见 ``app.services.ability_engine``).

    只产出真正有值的维度; ``source`` 落在占位家族 (stub / heuristic) 时 ``weight=0``,
    即画像 EWMA 不会因此动一分. T4 的 ``ability_events`` 直接吃这个列表.
    """
    pairs: tuple[tuple[Dimension, float | None], ...] = (
        ("pronunciation", grade.pronunciation),
        ("fluency", grade.fluency),
        ("grammar", grade.grammar),
        ("vocabulary", grade.vocabulary),
    )
    stubbed = grade.source in _STUB_SOURCES
    events: list[AbilityEvidence] = []
    for dimension, value in pairs:
        if value is None:
            continue
        events.append(
            AbilityEvidence(
                dimension=dimension,
                score=value,
                source=grade.source,
                weight=0.0 if stubbed else 1.0,
                ise_ref_mode=grade.ise_ref_mode if dimension == "pronunciation" else None,
            )
        )
    return events


# P3 (T4) 落位说明: P2 留在这里的 ``record_step_evidence`` 空钩子已兑现为
# :func:`app.services.ability_engine.record_step_evidence` (EWMA + 事件流水真实现).
# 端点改为直接引用 ability_engine 的同名函数 (两个模块有向依赖: ability_engine ->
# drill_grader 只吃 :class:`AbilityEvidence` 类型, 反向 import 会成环).


__all__ = sorted(
    [
        "ANSWER_MAX_CHARS",
        "AbilityEvidence",
        "Dimension",
        "DrillGrade",
        "DrillMistake",
        "IseRefMode",
        "LlmUnavailableError",
        "PASS_SCORE",
        "SKIP_SOURCE",
        "TextStepKind",
        "ability_evidence",
        "grade_make_sentence",
        "grade_read_along",
        "grade_retell",
        "grade_step",
        "grade_translate",
        "resolve_answer_text",
        "transcribe_audio",
    ]
)

"""drill 评分引擎测试 (§5.4 四题型 + §5.5 LLM 判分模式).

三件事各自都要有证据:

1. **无凭据也能跑完**: conftest 把所有凭据清空, 跟读走 StubASR (标 ``source="stub"``),
   三个 LLM 题型退回确定性启发式 (标 ``source="heuristic"`` + ``llm_source="stub"``),
   且降级分可复现.
2. **LLM 判分真的在校验**: 用 ``monkeypatch`` 换掉 ``AsyncOpenAI`` (沿用
   ``tests/test_llm_endpoints.py`` 的做法), 断言每题恰好 1 次调用、坏 JSON 时**回喂错误
   重试 1 次**、再失败就降级并留 WARNING.
3. **T2 内容契约没破**: translate 题的中文在 ``ref_text`` —— 中文只进 prompt,
   **绝不进 ISE**; ISE 只在 read_along 上调.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from loguru import logger

from app.core.errors import AppError
from app.models.course import FoundationStep
from app.services import drill_grader as dg
from app.services import llm_provider
from app.services.interfaces import AsrResult, AsrWord


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.fixture
def warnings_sink() -> Iterator[list[str]]:
    """抓 loguru 的 WARNING (降级必须留痕, 不然线上悄悄掉分没人知道)."""
    bag: list[str] = []
    sink_id = logger.add(lambda message: bag.append(str(message)), level="WARNING")
    yield bag
    logger.remove(sink_id)


# ------------------------------------------------------------------ 测试料


def step_read_along(ref_text: str = "Can I get a medium coffee?", **over: Any) -> FoundationStep:
    payload: dict[str, Any] = {
        "id": "f1",
        "type": "read_along",
        "cn_prompt": "跟我读这句点单开场。",
        "ref_text": ref_text,
        "translation_cn": "我要一杯中杯咖啡。",
        "accept_notes": "词尾 /m/ 到位即可。",
    }
    payload.update(over)
    return FoundationStep.model_validate(payload)


def step_retell(**over: Any) -> FoundationStep:
    payload: dict[str, Any] = {
        "id": "f3",
        "type": "retell",
        "cn_prompt": "把这单咖啡的要求说出来。",
        "ref_text": "I want a medium coffee with cream and no sugar. I'll take it to go.",
        "translation_cn": "我要中杯咖啡, 加奶不加糖, 带走。",
        "reference_answer": "Medium coffee with cream, no sugar, to go.",
        "accept_notes": "说出杯型、奶/糖、to go 三个信息点即算通过。",
    }
    payload.update(over)
    return FoundationStep.model_validate(payload)


def step_translate(**over: Any) -> FoundationStep:
    payload: dict[str, Any] = {
        "id": "f4",
        "type": "translate",
        "cn_prompt": "说成英文：一共多少钱？",  # noqa: RUF001
        "ref_text": "一共多少钱？",  # noqa: RUF001  (T2 契约: 中文原句在 ref_text)
        "reference_answer": "How much is that in total?",
        "accept_notes": "How much 开头即算通过。",
    }
    payload.update(over)
    return FoundationStep.model_validate(payload)


def step_make_sentence(**over: Any) -> FoundationStep:
    payload: dict[str, Any] = {
        "id": "f6",
        "type": "make_sentence",
        "cn_prompt": "用 add 说一句你想再加点什么。",
        "target_word": "add",
        "reference_answer": "Actually, add a cookie, please.",
        "accept_notes": "含 add 并说出要加的东西即算通过。",
    }
    payload.update(over)
    return FoundationStep.model_validate(payload)


class FakeASR:
    """记 spy 的假 ISE: 断言"中文从没进过 ISE"要靠它."""

    def __init__(self, scores: float = 88.0, source: str = "xunfei") -> None:
        self.scores = scores
        self.source = source
        self.calls: list[tuple[str, str]] = []

    async def recognize(
        self, audio: bytes, ref_text: str, category: str = "read_sentence"
    ) -> AsrResult:
        self.calls.append((ref_text, category))
        words = ref_text.split()
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=w, score=self.scores, ipa=None) for w in words],
            source=self.source,
        )


class BarrierISE:
    """假 ISE: 两个请求都走进 recognize 才一起放行.

    用来把"两个并发 /step 都读到了同一份快照、都还没写回"这个窗口对齐出来 ——
    并发的正确性不能靠运气排布 await 点 (见 tests/test_course_sessions.py 的并发用例).
    """

    def __init__(self, barrier: asyncio.Barrier) -> None:
        self._barrier = barrier

    async def recognize(
        self, audio: bytes, ref_text: str, category: str = "read_sentence"
    ) -> AsrResult:
        del audio, category
        await asyncio.wait_for(self._barrier.wait(), timeout=5)
        words = ref_text.split()
        return AsrResult(
            recognized=ref_text,
            word_scores=[AsrWord(word=w, score=90.0, ipa=None) for w in words],
            source="stub",
        )


class FakeIAT:
    """假 IAT: 返回固定转写 (讯飞没有 stub, 但测试要能走"有转写"这条分支)."""

    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm: bytes) -> str | None:
        del pcm
        self.calls += 1
        return self.text


PCM = b"\x00\x01" * 3200  # 200ms @ PCM L16 16kHz mono


class _FakeCompletions:
    def __init__(self, client: _FakeOpenAI) -> None:
        self._client = client

    async def create(self, **kwargs: Any) -> Any:
        self._client.requests.append(kwargs)
        reply = self._client.next_reply()
        if isinstance(reply, Exception):
            raise reply

        class _Msg:
            content: ClassVar[str] = ""

        message = _Msg()
        message.content = reply  # type: ignore[attr-defined]

        class _Choice:
            pass

        choice = _Choice()
        choice.message = message  # type: ignore[attr-defined]

        class _Resp:
            pass

        resp = _Resp()
        resp.choices = [choice]  # type: ignore[attr-defined]
        resp.model = "qwen3.8-max"  # type: ignore[attr-defined]
        return resp


class _FakeChat:
    def __init__(self, client: _FakeOpenAI) -> None:
        self.completions = _FakeCompletions(client)


class _FakeOpenAI:
    """替掉 ``llm_provider.AsyncOpenAI``: 按脚本吐 content, 并记下每次请求."""

    def __init__(self, replies: list[Any]) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.chat = _FakeChat(self)

    def next_reply(self) -> Any:
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0] if self._replies else RuntimeError("no canned reply")

    def with_options(self, **kwargs: Any) -> _FakeOpenAI:
        self.options = kwargs  # type: ignore[attr-defined]
        return self


def install_llm(monkeypatch: pytest.MonkeyPatch, replies: list[Any]) -> _FakeOpenAI:
    """配好"有 LLM 凭据"的环境并把客户端换成假的 (与 test_llm_endpoints 同套路)."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "llm_default_model", "qwen3.8-max")
    client = _FakeOpenAI(replies)
    monkeypatch.setattr(llm_provider, "AsyncOpenAI", lambda **kwargs: client)
    llm_provider.reset_llm_provider_for_tests()
    return client


def _user_prompt(client: _FakeOpenAI, index: int = 0) -> str:
    return str(client.requests[index]["messages"][-1]["content"])


# ============================================================ read_along


@pytest.mark.asyncio
async def test_read_along_scores_through_the_ise_pipeline() -> None:
    asr = FakeASR(scores=90.0)
    grade = await dg.grade_read_along(step_read_along(), PCM, asr=asr)
    assert grade.step_type == "read_along"
    assert grade.source == "xunfei"
    assert grade.pronunciation == pytest.approx(90.0)
    assert grade.fluency is not None and grade.completeness == pytest.approx(100.0)
    assert grade.grammar is None and grade.vocabulary is None  # 跟读不给语法/词汇证据
    assert grade.ise_ref_mode == "exact_reference"
    assert grade.llm_source is None
    assert grade.speech_rate_wpm and grade.speech_rate_wpm > 0
    assert [w.score for w in grade.word_details] == [90.0] * len(grade.word_details)
    assert grade.transcript == "Can I get a medium coffee?"
    assert asr.calls == [("Can I get a medium coffee?", "read_sentence")]


@pytest.mark.asyncio
async def test_read_along_marks_stub_source_when_xunfei_falls_back() -> None:
    asr = FakeASR(scores=95.0, source="stub")
    grade = await dg.grade_read_along(step_read_along(), PCM, asr=asr)
    assert grade.source == "stub" and grade.passed


@pytest.mark.asyncio
async def test_read_along_without_audio_is_a_400() -> None:
    with pytest.raises(AppError) as exc:
        await dg.grade_read_along(step_read_along(), b"", asr=FakeASR())
    assert exc.value.status_code == 400 and exc.value.code == "AUDIO_REQUIRED"


@pytest.mark.asyncio
async def test_read_along_without_ref_text_is_a_400() -> None:
    step = step_read_along(ref_text="   ")
    with pytest.raises(AppError) as exc:
        await dg.grade_read_along(step, PCM, asr=FakeASR())
    assert exc.value.code == "STEP_CONTENT_INVALID"


@pytest.mark.asyncio
async def test_read_along_uses_the_default_provider_and_stays_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没凭据时默认 provider 自己回退 StubASR: 分数照给, source 必须是 stub."""
    grade = await dg.grade_read_along(step_read_along(), PCM)
    assert grade.source == "stub"
    assert grade.score > 0


# ============================================================ 无 LLM 凭据的降级


@pytest.mark.asyncio
async def test_retell_without_creds_uses_deterministic_heuristic() -> None:
    step = step_retell()
    good = "A medium coffee with cream, no sugar, and it's to go."
    first = await dg.grade_retell(step, good)
    second = await dg.grade_retell(step, good)
    assert first.model_dump() == second.model_dump()  # 完全确定性
    assert first.source == "heuristic" and first.llm_source == "stub"
    assert first.passed and first.vocabulary == first.score and first.grammar is None
    assert first.feedback_cn.startswith("LLM 未配置")
    assert "coffee" in first.key_points_hit


@pytest.mark.asyncio
async def test_retell_heuristic_fails_an_off_topic_answer() -> None:
    grade = await dg.grade_retell(step_retell(), "The weather is nice today.")
    assert not grade.passed and grade.score < dg.PASS_SCORE


@pytest.mark.asyncio
async def test_translate_heuristic_compares_english_against_english() -> None:
    grade = await dg.grade_translate(step_translate(), "How much is that in total?")
    assert grade.passed
    assert grade.grammar == grade.score and grade.vocabulary == grade.score
    assert grade.mistakes == []


@pytest.mark.asyncio
async def test_make_sentence_heuristic_needs_the_target_word() -> None:
    with_target = await dg.grade_make_sentence(step_make_sentence(), "Please add a cookie.")
    without = await dg.grade_make_sentence(step_make_sentence(), "One coffee, thanks.")
    assert with_target.passed and without.score == 30.0 and not without.passed


@pytest.mark.asyncio
async def test_answer_length_band_penalties() -> None:
    """长度带: 只说一个词 (没内容) 比说全了要低, 灌水超长也要扣."""
    step = step_retell()
    tiny = await dg.grade_retell(step, "Coffee")
    full = await dg.grade_retell(step, "A medium coffee with cream, no sugar, to go.")
    padded = await dg.grade_retell(
        step,
        " ".join(["a medium coffee with cream no sugar to go"] * 6),
    )
    assert tiny.score < full.score
    assert padded.score == pytest.approx(full.score - 10.0, abs=0.11)


@pytest.mark.asyncio
async def test_empty_answer_is_a_400_not_a_fake_pass() -> None:
    with pytest.raises(AppError) as exc:
        await dg.grade_step(step=step_retell(), answer_text="   ")
    assert exc.value.code == "ANSWER_REQUIRED"


# ============================================================ LLM 判分


@pytest.mark.asyncio
async def test_retell_llm_grade_uses_one_call_and_keeps_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = install_llm(
        monkeypatch,
        [
            json.dumps(
                {
                    "score": 82,
                    "feedback_cn": "三个要点都说了, 语速再稳一点。",
                    "key_points_hit": ["medium coffee", "no sugar", "to go"],
                }
            )
        ],
    )
    grade = await dg.grade_retell(step_retell(), "Medium coffee, no sugar, to go.")
    assert len(client.requests) == 1
    assert grade.source == "llm" and grade.llm_source == "qwen3.8-max"
    assert grade.score == pytest.approx(82.0) and grade.passed
    assert grade.key_points_hit == ["medium coffee", "no sugar", "to go"]
    assert grade.feedback_cn.startswith("三个要点")
    prompt = _user_prompt(client)
    assert "参考要点" in prompt and "评分要点" in prompt  # accept_notes 当 rubric 进去了
    assert client.requests[0]["temperature"] == 0.2
    assert client.requests[0]["model"] == "qwen3.8-max"


@pytest.mark.asyncio
async def test_translate_prompt_shows_chinese_as_the_question_not_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T2 契约: 中文是题目, 参考英文才是答案."""
    client = install_llm(
        monkeypatch,
        [
            json.dumps(
                {
                    "score": 74,
                    "feedback_cn": "少了 in total。",
                    "mistakes": [
                        {
                            "source_cn": "一共",
                            "said": "How is it?",
                            "better": "How much is it in total?",
                            "explanation_cn": "问价格用 how much。",
                        }
                    ],
                }
            )
        ],
    )
    grade = await dg.grade_translate(step_translate(), "How is it?")
    prompt = _user_prompt(client)
    assert "中文原句 (题目, 不是答案): 一共多少钱？" in prompt  # noqa: RUF001
    assert "参考译文: How much is that in total?" in prompt
    assert grade.mistakes and grade.mistakes[0].better == "How much is it in total?"
    assert grade.mistakes[0].explanation_cn.startswith("问价格")


@pytest.mark.asyncio
async def test_translate_never_sends_chinese_into_ise(monkeypatch: pytest.MonkeyPatch) -> None:
    """中文 ``ref_text`` 绝不会出现在送 ISE 的参考文本里 (只调 read_along 才碰 ISE)."""
    spy = FakeASR()
    monkeypatch.setattr(dg, "_IAT", FakeIAT("How much altogether?"))
    install_llm(monkeypatch, [json.dumps({"score": 66, "feedback_cn": "能听懂"})])
    await dg.grade_step(step=step_translate(), audio_bytes=PCM)
    assert spy.calls == []  # ISE 一次没调
    assert isinstance(dg._IAT, FakeIAT)


@pytest.mark.asyncio
async def test_make_sentence_llm_judges_target_word_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = install_llm(
        monkeypatch,
        [json.dumps({"score": 45, "feedback_cn": "add 用法不对", "used_target_word": False})],
    )
    grade = await dg.grade_make_sentence(step_make_sentence(), "I add a cookie.")
    assert not grade.passed
    assert grade.key_points_hit == []
    assert "目标词: add" in _user_prompt(client)


@pytest.mark.asyncio
async def test_bad_json_is_retried_once_with_the_error_fed_back(
    monkeypatch: pytest.MonkeyPatch,
    warnings_sink: list[str],
) -> None:
    good = json.dumps({"score": 71, "feedback_cn": "行", "key_points_hit": ["coffee"]})
    client = install_llm(monkeypatch, ["这不是 JSON", good])
    grade = await dg.grade_retell(step_retell(), "A medium coffee to go.")
    assert len(client.requests) == 2
    assert grade.source == "llm" and grade.score == pytest.approx(71.0)
    retry_turns = client.requests[1]["messages"]
    assert retry_turns[-2]["role"] == "assistant" and retry_turns[-2]["content"] == "这不是 JSON"
    assert "上一条输出不合格" in retry_turns[-1]["content"]
    assert any("retrying once" in line for line in warnings_sink)


@pytest.mark.asyncio
async def test_validation_error_is_part_of_the_retry_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = json.dumps({"score": 60, "feedback_cn": "及格线"})
    client = install_llm(monkeypatch, [json.dumps({"score": 250, "feedback_cn": "超范围"}), good])
    grade = await dg.grade_retell(step_retell(), "A medium coffee to go.")
    assert grade.score == pytest.approx(60.0)
    assert "less_than_or_equal" in client.requests[1]["messages"][-1]["content"] or "250" in str(
        client.requests[1]["messages"][-1]["content"]
    )


@pytest.mark.asyncio
async def test_second_bad_output_degrades_to_heuristic_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    warnings_sink: list[str],
) -> None:
    client = install_llm(monkeypatch, ["garbage one", "garbage two"])
    grade = await dg.grade_retell(step_retell(), "A medium coffee to go.")
    assert len(client.requests) == 2  # 只重试一次, 不做第三次
    assert grade.source == "heuristic" and grade.llm_source == "stub"
    assert grade.feedback_cn.startswith("LLM 判分失败")
    assert any("malformed" in line for line in warnings_sink)


@pytest.mark.asyncio
async def test_llm_transport_error_degrades_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = install_llm(monkeypatch, [RuntimeError("upstream 502")])
    grade = await dg.grade_translate(step_translate(), "How much?")
    assert len(client.requests) == 1  # 网络失败不在学员身上重试
    assert grade.source == "heuristic" and grade.feedback_cn.startswith("LLM 判分失败")


@pytest.mark.asyncio
async def test_fenced_json_and_prose_wrappers_are_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_llm(
        monkeypatch,
        ['```json\n{"score": 64, "feedback_cn": "还行", "key_points_hit": ["go"]}\n```'],
    )
    grade = await dg.grade_retell(step_retell(), "Two to go.")
    assert grade.score == pytest.approx(64.0) and grade.source == "llm"


def test_parse_llm_json_edge_cases() -> None:
    assert dg._parse_llm_json('{"score": 1}') == {"score": 1}
    assert dg._parse_llm_json('```json\n{"score": 2}\n```') == {"score": 2}
    assert dg._parse_llm_json('好的, 这是结果:\n{"score": 3}\n希望有帮助') == {"score": 3}
    for bad in ("完全不像 JSON", "[1,2,3]", ""):
        with pytest.raises(ValueError):
            dg._parse_llm_json(bad)


# ============================================================ 语音输入 / 分派


@pytest.mark.asyncio
async def test_audio_only_answer_with_transcript_is_graded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iat = FakeIAT("Medium coffee, no sugar, to go.")
    install_llm(monkeypatch, [json.dumps({"score": 88, "feedback_cn": "全说到了"})])
    grade = await dg.grade_step(step=step_retell(), audio_bytes=PCM, iat=iat)
    assert iat.calls == 1
    assert grade.transcript == "Medium coffee, no sugar, to go."


@pytest.mark.asyncio
async def test_audio_only_without_iat_credentials_is_a_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dg, "_IAT", FakeIAT(None))
    with pytest.raises(AppError) as exc:
        await dg.grade_step(step=step_retell(), audio_bytes=PCM)
    assert exc.value.code == "TRANSCRIPT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_text_wins_over_audio_when_both_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iat = FakeIAT("should not be used")
    install_llm(monkeypatch, [json.dumps({"score": 70, "feedback_cn": "按文本判"})])
    grade = await dg.grade_step(
        step=step_retell(), audio_bytes=PCM, answer_text="Coffee to go.", iat=iat
    )
    assert iat.calls == 0
    assert grade.transcript == "Coffee to go."


@pytest.mark.asyncio
async def test_grade_step_rejects_unknown_step_type() -> None:
    step = step_retell()
    object.__setattr__(step, "type", "dictation")  # 绕过 Literal 造脏数据
    with pytest.raises(AppError) as exc:
        await dg.grade_step(step=step, answer_text="x")
    assert exc.value.code == "STEP_TYPE_UNSUPPORTED"


# ============================================================ §5.6 维度证据


@pytest.mark.asyncio
async def test_ability_evidence_gates_stub_scores_to_zero_weight() -> None:
    asr_stub = FakeASR(scores=95.0, source="stub")
    stubbed = dg.ability_evidence(await dg.grade_read_along(step_read_along(), PCM, asr=asr_stub))
    assert stubbed and all(event.weight == 0.0 for event in stubbed)

    real = dg.ability_evidence(
        await dg.grade_read_along(step_read_along(), PCM, asr=FakeASR(scores=70.0))
    )
    assert {event.dimension for event in real} >= {"pronunciation", "fluency"}
    assert all(event.weight == 1.0 for event in real)
    pron = next(event for event in real if event.dimension == "pronunciation")
    assert pron.ise_ref_mode == "exact_reference"


@pytest.mark.asyncio
async def test_ability_evidence_only_lists_dimensions_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_llm(monkeypatch, [json.dumps({"score": 77, "feedback_cn": "复述不错"})])
    events = dg.ability_evidence(await dg.grade_retell(step_retell(), "Coffee to go."))
    assert [(e.dimension, e.weight) for e in events] == [("vocabulary", 1.0)]


def test_record_step_evidence_moved_to_ability_engine() -> None:
    """P3 (T4) 兑现了 P2 留的空钩子: 实现搬去 ``ability_engine`` (drill 里没有僵尸).

    ``ability_engine`` 反过来 import ``drill_grader.AbilityEvidence`` —— 若实现留在
    drill 会成环, 所以端点从 ``app.api.v1.course_sessions.record_step_evidence``
    (import 自 ``app.services.ability_engine``) 取真身, 见
    ``tests/test_ability_engine.py``.
    """
    from app.services import ability_engine

    assert not hasattr(dg, "record_step_evidence")
    assert callable(ability_engine.record_step_evidence)


# ============================================================ 边界与降级细节


def test_stem_normalises_common_inflections() -> None:
    """降级分的词干归一化: 参考侧与作答侧要归到同一个键."""
    assert dg._stem("ordering") == "order"
    assert dg._stem("wanted") == "want"
    assert dg._stem("studies") == "study"
    assert dg._stem("changes") == "change"
    assert dg._stem("add") == "add"  # 太短不动, 免得把 "ad" 当成词干
    assert dg._stem("class") == "class"  # -ss 结尾不剥 s


def test_matched_terms_needs_both_sides() -> None:
    assert dg._matched_terms("", "coffee to go") == (0.0, [])
    assert dg._matched_terms("coffee", "") == (0.0, [])
    assert dg._overlap_score("coffee", "")[0] == 0.0


def test_dimensions_for_read_along_is_empty() -> None:
    assert dg._dimensions_for("read_along", 95.0) == {}


@pytest.mark.asyncio
async def test_read_along_rejects_ref_text_beyond_the_ise_limit() -> None:
    """ISE 参考文本硬上限 2000 字 (T2 契约), 超了要 400 而不是送上去被上游拒."""
    step = FoundationStep.model_construct(
        id="f1", type="read_along", cn_prompt="跟读", ref_text="word " * 500
    )
    with pytest.raises(AppError) as exc:
        await dg.grade_read_along(step, PCM, asr=FakeASR())
    assert exc.value.code == "REF_TEXT_TOO_LONG"


@pytest.mark.asyncio
async def test_transcribe_audio_skips_empty_payload() -> None:
    assert await dg.transcribe_audio(b"") is None


@pytest.mark.asyncio
async def test_llm_empty_feedback_falls_back_and_marks_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型不给点评/要点时, 服务端补一句可用的中文提示, 并自己记目标词."""
    install_llm(monkeypatch, [json.dumps({"score": 84, "feedback_cn": ""})])
    grade = await dg.grade_make_sentence(step_make_sentence(), "Please add a cookie to it.")
    assert grade.feedback_cn == "目标词用法正确。"
    assert grade.key_points_hit == ["add"]


@pytest.mark.asyncio
async def test_retry_with_still_invalid_fields_degrades(
    monkeypatch: pytest.MonkeyPatch, warnings_sink: list[str]
) -> None:
    """两次都过不了 pydantic (分数越界) -> 降级, 且把失败原因留进 WARNING."""
    client = install_llm(
        monkeypatch,
        [json.dumps({"score": 250}), json.dumps({"score": -5})],
    )
    grade = await dg.grade_retell(step_retell(), "A medium coffee to go.")
    assert len(client.requests) == 2
    assert grade.source == "heuristic" and grade.llm_source == "stub"
    assert any("degraded to heuristic" in line for line in warnings_sink)
    assert any("字段仍不合规" in line for line in warnings_sink)  # 降级原因也进日志


def test_parse_llm_json_rejects_unparseable_object_slice() -> None:
    # 找不到闭合括号
    with pytest.raises(ValueError, match="找不到 JSON 对象"):
        dg._parse_llm_json('{"score": ')
    # 截出来的那截本身不是合法 JSON
    with pytest.raises(ValueError, match="JSON 解析失败"):
        dg._parse_llm_json('结果如下 {"score": 88,} 希望有帮助')

"""端到端时延契约 (计划 §1 R2 / §P5) —— 同步 HTTP 处理里的每条 LLM 路径都必须有硬预算.

这里钉的是**一类 bug**, 不是一个函数: ``POST /sessions/{id}/finish-mission`` 曾经过
完课却永远看不到总评 —— 该请求同步调总评 LLM, 既无 ``timeout=`` 覆盖也无
``asyncio.wait_for``, 叠上 provider 层 ``max_retries=2`` 与坏 JSON 的回喂重试,
最坏 ~125s; 手机 OkHttp ``readTimeout`` 只有 30s, 于是**服务端把活干完了 (报告已落库,
还打了 "review copy degraded to deterministic"), 客户端却已经断开**。生产日志
(session 719833d1…, 2026-09-10) 里 68s 降级 + 200 OK 从未出现 + 用户猛点收工吃 4 连 409。

既有测试为什么看不见它: 所有 LLM 路径都被 ``install_llm`` 换成**即时返回**的假客户端,
时延在这个面上是**零维**的 —— 所以本文件故意不做"fake 立刻返回"的假设, 而是让假
LLM **慢过预算**, 再断言两件事:

1. **在预算内出结果** (墙钟 < 数秒, 不是数十秒) —— 这才对得上客户端的 30s;
2. **降级而不是 500** —— ``TimeoutError`` 必须在 :func:`_judge` 内部翻成
   ``LlmUnavailableError``; 四个同步调用点 (``_graded_text_step`` /
   ``build_review_report`` / ``polish_text`` / ``judge_level``) 只
   ``except LlmUnavailableError``, 逃逸的 ``TimeoutError`` 会把"降级"变成 500,
   **比不加预算更糟** (这就是 §6 风险表里那条 `[P5]` 陷阱)。

外加两条静态锁: ``max_retries`` 必须为 0 (否则任何 ``timeout=`` 都不是真实上限),
以及**新增**的 ``_judge`` 调用点不写预算就直接红 (AST 扫全 ``app/``, 后台作业模块
``course_generator`` 显式豁免 —— 它是 202 + 轮询, 30s 对它不成立)。

§P6 之后本文件还多钉一件事: 收工路径**只许**在请求里算纯算术的数值骨架, 总评文案移出
请求 → 于是总评有**两个**预算 (同步组合 20s / 后台作业 45s), 各自的调用点点名各自的常量,
求和表里 "finish-mission" 只剩 DB 往返 (:func:`test_no_endpoint_waits_on_the_review_llm_any_more`
+ :func:`test_review_budgets_split_sync_composition_from_background_job`)。作业自身的终态
与降级见 ``tests/test_review_async.py``。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient

from app.api.v1 import course_sessions as cs
from app.config import settings
from app.models.course import FoundationStep, SceneCourse
from app.services import assessment_engine as ae
from app.services import drill_grader as dg
from app.services import llm_provider
from app.services import mission_engine as me
from app.services.llm_provider import LlmMessage
from tests.test_scene_store import make_course_dict

#: 客户端事实: OkHttp readTimeout=30s (android/.../di/NetworkModule.kt, 无 callTimeout).
CLIENT_READ_TIMEOUT_S = 30.0
#: 契约里的固定余量 (序列化 / DB / 调度抖动 / 网关).
MARGIN_S = 5.0

#: 假 LLM 的"挂死"时长: 远大于所有预算, 又不至于让挂掉的用例拖慢整轮 CI.
HANG_S = 5.0
#: 被打断用的短预算 (证明"预算真的会触发", 不代表生产取值 —— 生产值见求和测试).
TINY_BUDGET_S = 0.3

APP_ROOT = Path(dg.__file__).resolve().parent.parent

_RETELL_JSON = json.dumps(
    {"score": 82.0, "feedback_cn": "要点说全了。", "key_points_hit": ["medium coffee"]},
    ensure_ascii=False,
)
_REVIEW_JSON = json.dumps(
    {
        "highlights": ["把点单和问价都说出口了。"],
        "improvements": ["语法: 特殊疑问句语序再练一轮。"],
    },
    ensure_ascii=False,
)


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


# ------------------------------------------------------------------ 慢 LLM 假面


class _SlowCompletions:
    def __init__(self, client: _SlowOpenAI) -> None:
        self._client = client

    async def create(self, **kwargs: Any) -> Any:
        client = self._client
        client.requests.append(kwargs)
        delay, reply = client.next_step()
        if delay:
            # 真链路上这里是"qwen 免费额度限速 / 上游挂死"; 挂死时永不返回 reply.
            await asyncio.sleep(delay)
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
        resp.model = "qwen3.8-flash"  # type: ignore[attr-defined]
        return resp


class _SlowChat:
    def __init__(self, client: _SlowOpenAI) -> None:
        self.completions = _SlowCompletions(client)


class _SlowOpenAI:
    """按脚本 ``(delay_s, content)`` 吐内容的假 ``AsyncOpenAI`` (最后一条无限重复).

    与 ``tests.test_drill_grader._FakeOpenAI`` 同一个接缝 (换掉 SDK 客户端), 区别只有
    一个: **它会真的慢**。这样测的就是预算, 不是解析。
    """

    def __init__(self, script: Sequence[tuple[float, Any]]) -> None:
        self._script = list(script) or [(0.0, RuntimeError("no canned reply"))]
        self.requests: list[dict[str, Any]] = []
        self.options: dict[str, Any] = {}
        self.chat = _SlowChat(self)  # type: ignore[assignment]

    def next_step(self) -> tuple[float, Any]:
        if len(self._script) > 1:
            return self._script.pop(0)
        return self._script[0]

    @property
    def calls(self) -> int:
        return len(self.requests)

    def with_options(self, **kwargs: Any) -> _SlowOpenAI:
        self.options.update(kwargs)
        return self


def install_slow_llm(
    monkeypatch: pytest.MonkeyPatch, script: Sequence[tuple[float, Any]]
) -> _SlowOpenAI:
    """配好"有 LLM 凭据"的环境, 并把客户端换成会慢的假的 (与 ``install_llm`` 同套路)."""
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "llm_default_model", "qwen3.8-flash")
    client = _SlowOpenAI(script)
    monkeypatch.setattr(llm_provider, "AsyncOpenAI", lambda **kwargs: client)
    llm_provider.reset_llm_provider_for_tests()
    return client


def _hanging(monkeypatch: pytest.MonkeyPatch) -> _SlowOpenAI:
    """一次调用都不返回的 LLM (上游挂死 = 本次要防的那一类故障)."""
    return install_slow_llm(monkeypatch, [(HANG_S, "")])


def shrink_budget(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> None:
    """把某个模块**实际查找**的预算常量改小 (只测"预算会触发", 不动生产取值)。

    坑: 调用点是 ``from drill_grader import NAME``, 名字绑在**消费方**模块的命名空间里
    —— 改 ``drill_grader`` 上的同名常量对 ``mission_engine`` 的调用点无效 (只会让用例
    慢慢跑完再红)。所以这里显式传消费方模块, 并强制断言名字真的存在。
    求和测试 (:func:`test_worst_case_sum_of_each_sync_path_fits_under_30s`) 读的仍是
    ``drill_grader`` 里的规范值 —— 那才是生产数。
    """
    assert hasattr(module, name), f"{module.__name__} 上没有 {name} —— 改错命名空间了"
    monkeypatch.setattr(module, name, TINY_BUDGET_S)


def _retell_step() -> FoundationStep:
    return FoundationStep.model_validate(
        {
            "id": "f3",
            "type": "retell",
            "cn_prompt": "把这单咖啡的要求说出来。",
            "ref_text": "I want a medium coffee with cream and no sugar.",
            "translation_cn": "我要中杯咖啡, 加奶不加糖。",
            "reference_answer": "Medium coffee with cream, no sugar.",
            "accept_notes": "说出杯型、奶/糖即算通过。",
        }
    )


async def _review() -> me.ReviewReport:
    course = SceneCourse.model_validate(make_course_dict())
    return await me.build_review_report(
        course=course,
        session_id="s-budget",
        mission={"turns": [], "tasks": [], "cleared": False, "turn_count": 0, "max_turns": 8},
        steps=[],
        ability_before=None,
        ability_after=None,
        briefing_passed=False,
    )


# ============================================================ 1) _judge 的预算语义


@pytest.mark.asyncio
async def test_judge_converts_budget_exceeded_into_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**本文件最重要的一条**: 超预算必须是 ``LlmUnavailableError``, 不能是 ``TimeoutError``.

    四个同步调用点只 ``except LlmUnavailableError`` —— 裸 ``TimeoutError`` 逃逸就是 500,
    比不封顶更糟 (§6 风险表 `[P5]` 那一行)。
    """
    _hanging(monkeypatch)
    started = time.monotonic()
    with pytest.raises(dg.LlmUnavailableError) as excinfo:
        await dg._judge(
            dg._SCHEMAS["retell"],
            [LlmMessage(role="user", content="x")],
            hard_budget_s=TINY_BUDGET_S,
        )
    elapsed = time.monotonic() - started
    assert not isinstance(excinfo.value, TimeoutError)
    assert type(excinfo.value) is dg.LlmUnavailableError
    assert isinstance(excinfo.value.__cause__, TimeoutError)  # 归因链留着, 日志能看出是超时
    assert "硬预算" in str(excinfo.value)
    assert elapsed < 3.0, f"预算没封顶住 (实际 {elapsed:.1f}s)"


@pytest.mark.asyncio
async def test_judge_budget_wraps_the_malformed_json_retry_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预算封的是**整个调用** (含坏 JSON 的回喂重试), 不是单次尝试.

    脚本: 第 1 次立刻回坏 JSON (触发重试), 第 2 次挂死 —— 若只把 ``wait_for`` 套在
    单次尝试上, 这里会永远等下去 (125s 那半边根因正是"重试不在墙内")。
    """
    client = install_slow_llm(
        monkeypatch,
        [(0.0, "我觉得这句话挺好的, 不是 JSON"), (HANG_S, "")],
    )
    started = time.monotonic()
    with pytest.raises(dg.LlmUnavailableError):
        await dg._judge(
            dg._SCHEMAS["retell"],
            [LlmMessage(role="user", content="x")],
            hard_budget_s=TINY_BUDGET_S,
        )
    assert time.monotonic() - started < 3.0
    assert client.calls == 2, "重试应发生在预算内 (第 2 次真的发出去了)"


@pytest.mark.asyncio
async def test_judge_without_budget_still_returns_slow_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hard_budget_s=None`` 保持旧语义 —— 后台作业 (整课生成) 故意不设墙.

    这条是豁免的**前提**: 30s 契约只对同步 handler 成立, 别把它错套到 240s/段的生成上
    (套了就是"整课骨架必然降级")。
    """
    install_slow_llm(monkeypatch, [(0.05, _RETELL_JSON)])
    judgement = await dg._judge(
        dg._SCHEMAS["retell"],
        [LlmMessage(role="user", content="x")],
    )
    assert judgement.score == pytest.approx(82.0)


@pytest.mark.asyncio
async def test_per_attempt_timeout_is_forwarded_and_retries_are_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``timeout=`` 要真的传到 SDK (并且 ``max_retries=0``, 下一条测), 否则它不是上限。"""
    client = install_slow_llm(monkeypatch, [(0.0, _RETELL_JSON)])
    _ = await dg._judge(
        dg._SCHEMAS["retell"],
        [LlmMessage(role="user", content="x")],
        hard_budget_s=dg.STEP_LLM_BUDGET_S,
    )
    assert client.options.get("timeout") == dg.LLM_TIMEOUT_S


# ============================================================ 2) provider 层不再偷偷补射


def test_llm_client_disables_silent_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """``max_retries`` 必须是 0: SDK 的重试会乘在 ``timeout`` 上, 让任何 ``timeout=``
    都不再是真实上限 (20s x 3 + 退避 ≈ 62s), 时延契约整个失效。
    """
    captured: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> _SlowOpenAI:
        captured.update(kwargs)
        return _SlowOpenAI([(0.0, "{}")])

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm_provider, "AsyncOpenAI", _capture)
    llm_provider.BailianOpenAIProvider()
    assert captured["max_retries"] == 0
    assert captured["timeout"] == pytest.approx(30.0)


def test_real_openai_client_carries_zero_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """真 SDK 对象上的属性检查 (防"参数写了但被 with_options 覆盖回去"这类写法错误)."""
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    provider = llm_provider.BailianOpenAIProvider()
    assert provider._client is not None
    assert provider._client.max_retries == 0


# ============================================================ 3) 四条同步路径: 降级, 不是 500


@pytest.mark.asyncio
async def test_graded_text_step_degrades_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文本步判分 (``POST /sessions/{id}/step``): 挂死的 LLM -> 退启发式分, 不抛。"""
    shrink_budget(monkeypatch, dg, "STEP_LLM_BUDGET_S")
    _hanging(monkeypatch)
    started = time.monotonic()
    grade = await dg.grade_retell(_retell_step(), "A medium coffee with cream, no sugar.")
    assert time.monotonic() - started < 3.0
    assert grade.source == "heuristic" and grade.llm_source == "stub"
    assert grade.feedback_cn.startswith("LLM 判分失败:")


@pytest.mark.asyncio
async def test_build_review_report_degrades_to_deterministic_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**同步组合** ``build_review_report`` 必须在预算内出报告 (脚本/测试的入口).

    §P6 之后端点不再走它: ``POST /sessions/{id}/finish-mission`` 只在请求里算数值骨架,
    文案改由后台作业补 —— 那两条路径 (202 的即时可读骨架、作业自己的 ``REVIEW_COPY_JOB_BUDGET_S``
    封顶与终态) 在 ``tests/test_review_async.py`` 里钉。本用例仍守着同步组合: 它是
    ``REVIEW_LLM_BUDGET_S`` (20s) 的唯一使用者, 也就是"如果哪天有人把它塞回请求里"时
    那堵 30s 墙的实际内容。

    断的不是"降级对不对" (既有行为, 生产日志已证它可用), 而是**多快**降级: 修复前
    ~68s, 而手机的 socket 在 30s 就死了, 于是报告落库了学员却永远看不到。
    """
    shrink_budget(monkeypatch, me, "REVIEW_LLM_BUDGET_S")
    _hanging(monkeypatch)
    started = time.monotonic()
    report = await _review()
    elapsed = time.monotonic() - started
    assert elapsed < 3.0, f"总评没在预算内返回 (实际 {elapsed:.1f}s, 客户端只等 30s)"
    assert report.source == "heuristic" and report.llm_source == "stub"
    # 降级只影响**文案**: 复盘页要拿到能渲染的诚实文案, 不能是空白。
    assert report.highlights and report.improvements


@pytest.mark.asyncio
async def test_polish_text_returns_absent_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """润色 (``POST /polish``): 没有确定性降级可言 -> 诚实返回 ``None``, 不是异常。"""
    shrink_budget(monkeypatch, me, "POLISH_BUDGET_S")
    _hanging(monkeypatch)
    started = time.monotonic()
    polish, source, llm_source = await me.polish_text("He go to meeting yesterday.")
    assert time.monotonic() - started < 3.0
    assert polish is None and source == "heuristic" and llm_source == "stub"


@pytest.mark.asyncio
async def test_judge_level_returns_none_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """判级 (``POST /assessment/{id}/complete``): 超时 = 诚实空态 (cefr=null, 零画像写入)。"""
    shrink_budget(monkeypatch, ae, "ASSESSMENT_JUDGE_BUDGET_S")
    _hanging(monkeypatch)
    facts = [
        {
            "no": "1",
            "type": "retell",
            "anchor": "A2",
            "prompt": "Say what you ordered.",
            "answer": "A medium coffee.",
            "key_points": "medium coffee",
            "ise": "",
        }
    ]
    started = time.monotonic()
    assert await ae.judge_level(facts, "") is None
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_mission_turn_still_degrades_after_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    """``judge_turn`` 的临时 ``wait_for`` 换成 ``hard_budget_s`` 后行为不变 (防重构回退)。

    它是这条契约的**模板** (docstring 早就写了"不封顶就是结构性『评分失败: timeout』");
    本次只是把强制点收敛到 :func:`_judge` 一处, 所以模板也得回头钉一遍。
    """
    _hanging(monkeypatch)
    course = SceneCourse.model_validate(make_course_dict())
    started = time.monotonic()
    judgement, source, llm_source = await me.judge_turn(
        course,
        [{"id": "t1", "required": True, "done": False, "hint_en": "Can I get a medium coffee?"}],
        [],
        "coffee please",
        1,
        hard_timeout_s=TINY_BUDGET_S,
    )
    assert time.monotonic() - started < 3.0
    assert source == "heuristic" and llm_source == "stub"
    assert judgement.reply  # 剧本下一行撑住对话, 不冷场


@pytest.mark.asyncio
async def test_polish_endpoint_degrades_instead_of_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP 面上的锁: 挂死的 LLM 只能让 ``/polish`` 变成 200 + ``polish=null``。

    ``TimeoutError`` 一旦从 ``_judge`` 逃逸, FastAPI 就把它变成 500 —— 那正是"加了预算
    反而比不加更糟"的形态 (§6 风险表 `[P5]`), 所以这条必须钉在端点上, 不只钉服务层。
    """
    shrink_budget(monkeypatch, me, "POLISH_BUDGET_S")
    _hanging(monkeypatch)
    res = await client.post("/api/v1/polish", json={"text": "He go to meeting yesterday."})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["polish"] is None and body["source"] == "heuristic"
    assert "未做润色" in body["note_cn"]


# ============================================================ 4) 契约的静态锁


#: 后台作业模块: 202 + 轮询, 30s readTimeout 对它不成立 -> 故意不设硬预算 (豁免要显式).
ASYNC_JOB_MODULES = frozenset({"course_generator.py"})


def _judge_call_sites() -> list[tuple[str, int, bool]]:
    """``(模块文件名, 行号, 是否显式传了 hard_budget_s)`` —— AST 扫全 ``app/``."""
    sites: list[tuple[str, int, bool]] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_judge":
                budgeted = any(kw.arg == "hard_budget_s" for kw in node.keywords)
                sites.append((path.name, node.lineno, budgeted))
    return sites


def test_every_sync_judge_call_site_declares_a_budget() -> None:
    """新增一条 ``_judge`` 调用而不写预算 -> 直接红 (R2: "没有默认值可躲")。

    这条是防止契约**再次腐化**的机器检查: 本次之前没有任何东西在问"这个 LLM 调用
    封顶了吗", 所以 7 个调用点里只有 2 个有预算。
    """
    sites = _judge_call_sites()
    assert len(sites) >= 5, f"AST 没扫到预期的调用点 ({sites}) —— 接缝大概被改了"
    unbudgeted = [(mod, line) for mod, line, ok in sites if not ok and mod not in ASYNC_JOB_MODULES]
    assert unbudgeted == [], (
        "这些同步路径的 LLM 调用没有硬预算, 最坏会拖过客户端 30s readTimeout: "
        f"{unbudgeted}; 给 _judge 传 hard_budget_s=*_BUDGET_S, 或 (确属后台作业) 把模块"
        "加进 ASYNC_JOB_MODULES 并说明为什么"
    )


def test_background_generation_is_still_explicitly_unbounded() -> None:
    """豁免是**显式**的, 不是漏网: 整课生成 240s/次, 本就不该被 30s 契约套住。"""
    from app.services import course_generator

    assert course_generator.GEN_TIMEOUT_S > CLIENT_READ_TIMEOUT_S
    assert all(not ok for mod, _line, ok in _judge_call_sites() if mod in ASYNC_JOB_MODULES)


def test_handler_still_passes_the_mission_turn_budget() -> None:
    """``LLM_TURN_BUDGET_S`` 必须仍然真的传进 ``judge_turn``; 漏传 = 该路径重新裸奔。"""
    assert "hard_timeout_s=LLM_TURN_BUDGET_S" in Path(cs.__file__).read_text(encoding="utf-8")


def test_budgets_are_named_constants_at_the_call_sites() -> None:
    """调用点必须引用常量名 (求和测试才读得到), 不许就地写字面量。

    第 5 项是 §P6 新加的**后台作业**: 它跟四个同步路径共用同一个 :func:`_judge` 预算接缝,
    但报的是另一个数 (``REVIEW_COPY_JOB_BUDGET_S``) —— 两个预算各自对应各自的墙, 所以
    两个调用点都得点名, 谁也不许顺手拿对方的常量。
    """
    for fn, name in (
        (dg._graded_text_step, "STEP_LLM_BUDGET_S"),
        (me.build_review_report, "REVIEW_LLM_BUDGET_S"),
        (me.polish_text, "POLISH_BUDGET_S"),
        (ae.judge_level, "ASSESSMENT_JUDGE_BUDGET_S"),
        (cs._run_review_copy_job, "REVIEW_COPY_JOB_BUDGET_S"),
    ):
        assert f"hard_budget_s={name}" in inspect.getsource(fn), (
            f"{fn.__name__} 应把硬预算写成 {name} (见 drill_grader 的硬预算块)"
        )


def test_worst_case_sum_of_each_sync_path_fits_under_30s() -> None:
    """契约求和: 同请求内 ``其它 await + budget + 5s 余量 <= 30s``。

    "其它 await" 取该请求里**已封顶**的部分 (语音轮读 ``course_sessions`` 的
    ``*_TURN_BUDGET_S``; DB/序列化算进余量)。求和**只许变小**: 已知装不下的那条
    列在 ``over_budget`` 并给了 ceiling 与归属, 涨上去就红。
    """
    # 音频步的 IAT 只有服务层自己的 8s + ws open_timeout 5s (调用点没包预算)。
    iat_service_worst_s = float(settings.xunfei_iat_timeout_s) + 5.0
    mission_turn_s = cs.IAT_TURN_BUDGET_S + max(cs.ISE_TURN_BUDGET_S, cs.LLM_TURN_BUDGET_S)

    fits: dict[str, float] = {
        "step (文本回答)": dg.STEP_LLM_BUDGET_S,
        "step (read_along: 只有 ISE)": float(settings.xunfei_ise_timeout_s),
        "mission 单轮": mission_turn_s,
        # §P6: 收工与"到轮次上限自动收工"都**不再同步等总评文案** —— 请求里只剩
        # DB/聚合, 文案交给后台作业。自动收工因此从下面的 over_budget 搬回这里:
        # 它的最坏时长就是那一轮本身的 mission_turn_s, 不再叠加一次总评 LLM。
        "finish-mission (202, 只有 DB/聚合)": 0.0,
        "mission 到轮次上限自动收工 (总评已异步)": mission_turn_s,
        "polish": dg.POLISH_BUDGET_S,
        "assessment/complete": dg.ASSESSMENT_JUDGE_BUDGET_S,
    }
    for name, worst in fits.items():
        assert worst + MARGIN_S <= CLIENT_READ_TIMEOUT_S, (
            f"{name} 最坏 {worst:.1f}s + {MARGIN_S:.0f}s 余量 已越过客户端 "
            f"{CLIENT_READ_TIMEOUT_S:.0f}s readTimeout"
        )

    # 已记录在案、本次**不**修的一条 (缘由见 drill_grader 硬预算块的 (*)).
    over_budget: dict[str, tuple[float, float]] = {
        # IAT 挂死的角落才吃穿余量 (常规 <=8s 时是 28s)。这是讯飞侧的调用点没包预算,
        # 不是 LLM 预算问题, 修法见 drill_grader 硬预算块的那一行注记。
        "step (音频作答: IAT 未包调用点预算)": (iat_service_worst_s + dg.STEP_LLM_BUDGET_S, 33.0),
    }
    assert set(over_budget) == {
        "step (音频作答: IAT 未包调用点预算)",
    }, "同步路径的'装不下'名单变了: 收紧预算或走异步, 别默默多一条超时路径"
    for name, (worst, ceiling) in over_budget.items():
        assert worst <= ceiling + 1e-6, (
            f"{name} 的最坏时长从 {ceiling}s 涨到 {worst:.1f}s —— 求和只能变小; "
            "确实要改就同步更新 drill_grader 硬预算块的表与本用例的 ceiling"
        )


def test_review_budgets_split_sync_composition_from_background_job() -> None:
    """§P6 之后总评有**两个**预算, 各管一件事, 谁也不能替谁背书。

    历史: 计划 §P5 曾建议把总评预算直接放到 45s —— 那只在"文案已经不在请求里"时
    成立。当时 ``finish-mission`` 还是同步的, 45 > 30 会把学员报的超时原样留下, 所以
    P5 把它压在 20s 并留了看门狗。P6 真的把文案搬进后台作业之后, 看门狗要盯的东西
    变了, 于是本用例取代它:

    * ``REVIEW_LLM_BUDGET_S`` (20s) 仍必须装得进 socket —— 它现在是**同步组合**
      ``build_review_report`` 的预算, 那个入口给脚本/测试用, 端点已不再走它;
    * ``REVIEW_COPY_JOB_BUDGET_S`` (45s) **故意**大于 socket 超时: 后台作业没有人在
      等它, 它的墙不是用来给 30s 交差的, 而是保证一条挂死的 LLM 不会把会话永远留在
      ``generating``。所以它必须存在、必须比同步预算大, 且必须真的被作业用上。
    """
    assert dg.REVIEW_LLM_BUDGET_S + MARGIN_S <= CLIENT_READ_TIMEOUT_S
    # 单次尝试的 socket 超时也必须单独装得进 30s: max_retries=0 之后它才是真上限。
    assert dg.LLM_TIMEOUT_S + MARGIN_S <= CLIENT_READ_TIMEOUT_S
    assert dg.REVIEW_COPY_JOB_BUDGET_S > dg.REVIEW_LLM_BUDGET_S, (
        "后台作业的预算若不比同步组合大, 异步化就没换来任何东西 —— 文案还是会在原来的时间内被砍掉"
    )
    # 重派水位必须真的给作业留够跑完的时间, 否则 GET 会在作业还在写时就再派一个。
    assert cs.REVIEW_REDISPATCH_AFTER_S >= dg.REVIEW_COPY_JOB_BUDGET_S


def test_no_endpoint_waits_on_the_review_llm_any_more() -> None:
    """机器检查: 收工路径里不许再出现"同步等总评文案"的调用。

    这是防止 R2 复发的看门狗 —— 本次事故的形状就是"某个端点里挂了一次没人封顶的
    LLM 调用"。端点只许调纯算术的 ``build_review_skeleton``; 会调 LLM 的
    ``build_review_report`` 只能出现在后台作业之外的脚本/测试入口。

    第二刀按**函数**切: 全文扫 ``build_review_report(`` 挡不住"在端点里直接 await
    ``mission_engine.review_copy(...)``"这种写法 —— 那才是把总评 LLM 塞回请求的最短路径
    (变异实测: 只有墙钟用例会红, 而墙钟用例很容易被当成 CI 抖动忽略)。作业自己也在本模块
    里调 ``review_copy``, 所以必须按函数体切范围, 不能按文件切。
    """
    src = Path(cs.__file__).read_text(encoding="utf-8")
    assert "build_review_skeleton(" in src, "收工路径应改用数值骨架"
    assert "build_review_report(" not in src, (
        "端点里又出现同步的 build_review_report —— 那会把总评 LLM 拉回请求里, "
        "学员报的 30s 超时原样复发"
    )
    # 文案只允许在后台作业里取, 且必须显式报作业预算。
    assert "hard_budget_s=REVIEW_COPY_JOB_BUDGET_S" in src

    tree = ast.parse(src)
    handlers = {"finish_mission", "_finish_mission_state", "submit_mission_turn"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name not in handlers:
            continue
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            called = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
            if called in {"build_review_report", "review_copy"}:
                offenders.append(f"{node.name}:{call.lineno} 等了 {called}()")
    assert offenders == [], (
        f"收工入口的函数体里出现了会等总评文案的调用: {offenders}; "
        "数值骨架落库 -> 202 -> 文案交给 run_review_copy_job, 别把它拉回请求里"
    )


def _direct_chat_call_sites() -> list[tuple[str, int, bool]]:
    """不走 :func:`_judge` 的**裸** ``provider.chat(...)`` 调用点 (dialogue 轮 / 开场白)."""
    sites: list[tuple[str, int, bool]] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "chat":
                has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                sites.append((path.name, node.lineno, has_timeout))
    return sites


def test_bare_provider_chat_calls_pass_an_explicit_timeout() -> None:
    """绕开 :func:`_judge` 的调用点也得显式写 ``timeout=`` —— 契约不允许"默认值兜底"。

    ``dialogue.py`` 自己组 prompt 而不用 ``_judge``, 所以它不受 ``hard_budget_s`` 保护;
    它的 ``timeout=`` 在 ``max_retries=0`` 之前是**假**上限 (12s 实为 36s), 本次把
    provider 的重试关掉之后才第一次是真的。这条锁防止将来再加裸调用时漏写超时。
    """
    sites = _direct_chat_call_sites()
    assert sites, "AST 没扫到任何 provider.chat() —— 接缝变了, 请同步改本用例"
    missing = [(mod, line) for mod, line, ok in sites if not ok]
    assert missing == [], f"这些 provider.chat() 没有显式 timeout: {missing}"

    from app.api.v1 import dialogue

    assert dialogue._VOICE_CALL_BUDGET_S + MARGIN_S <= CLIENT_READ_TIMEOUT_S
    assert dialogue._LLM_TURN_BUDGET_S + MARGIN_S <= CLIENT_READ_TIMEOUT_S
    assert dialogue._ISE_TASK_BUDGET_S + MARGIN_S <= CLIENT_READ_TIMEOUT_S

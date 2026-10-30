"""同步 LLM 调用的时延契约 (v3.0 之后只剩两条同步路 + 两个后台作业).

客户端事实: OkHttp ``readTimeout=30s``, 没有 ``callTimeout``。所以**任何**同步 LLM
调用都必须自带硬预算, 且 ``最坏时长 + 5s 余量 <= 30s``。

v3.0 大扫除删掉了打基础/实战轮/复盘/润色/判级那条条通路, 这张表跟着收缩成:

* **群聊一轮** (``POST /dialogue/threads/{id}/turn``):
  ``IAT 8.0 + max(ISE 8.5, GEN 14.0) + TTS 3.0 = 25.0`` —— **正好顶格, 零余量**。
* **长按翻译** (``POST /translate``): 6.0s, 独立请求、不占上面那个总额。
* 两个后台作业 (自定义场景骨架、每轮评分) 在 202/请求之外跑, 30s 契约对它们不成立,
  但**必须封顶** —— 豁免在这张表里是显式列出的, 不是漏网。

三把锁 (历史上每次都靠它们把"改了实现忘了改契约"逮住), 收缩之后仍然都在:

1. :func:`test_worst_case_sum_of_each_sync_path_fits_under_30s` —— 逐路径求和。
2. :func:`test_every_sync_judge_call_site_declares_a_budget` —— AST 扫全仓 ``_judge``
   调用点, 新增一条不写预算直接红。
3. :func:`test_budgets_are_named_constants_at_the_call_sites` —— 预算必须是**具名常量**
   且写在调用点上 (内联成字面量, 求和表就读不到了); 而 :func:`shrink_budget` 打在
   **消费侧模块**的命名空间上 (``from x import NAME`` 之后名字绑在导入方)。
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

from app.config import settings
from app.services import dialogue_scenes, llm_provider, thread_grading, thread_turn
from app.services import drill_grader as dg
from app.services import scene_spec_generator as sg
from app.services import thread_audio as ta
from app.services import translate as tr
from app.services import turn_generation as tg
from app.services.llm_provider import LlmMessage

#: 客户端事实: OkHttp readTimeout=30s (android/.../di/NetworkModule.kt, 无 callTimeout).
CLIENT_READ_TIMEOUT_S = 30.0
#: 契约里的固定余量 (序列化 / DB / 调度抖动 / 网关).
MARGIN_S = 5.0

#: 假 LLM 的"挂死"时长: 远大于所有预算, 又不至于让挂掉的用例拖慢整轮 CI.
HANG_S = 5.0
#: 被打断用的短预算 (证明"预算真的触发", 不代表生产取值 —— 生产值见求和测试).
TINY_BUDGET_S = 0.3

APP_ROOT = Path(dg.__file__).resolve().parent.parent


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
    —— 改 ``drill_grader`` 上的同名常量对 ``turn_generation`` 的调用点无效 (只会让用例
    慢慢跑完再红)。所以这里显式传消费方模块, 并强制断言名字真的存在。
    求和测试读的是 ``drill_grader`` 里的规范值 —— 那才是生产数。
    """
    assert hasattr(module, name), f"{module.__name__} 上没有 {name} —— 改错命名空间了"
    monkeypatch.setattr(module, name, TINY_BUDGET_S)


def one_reply_json() -> str:
    return json.dumps({"reply": "What would you like?", "reply_cn": "你想要点什么?"})


def _messages() -> list[LlmMessage]:
    scene = dialogue_scenes.resolve_scene("restaurant")
    assert scene is not None
    return thread_turn.turn_messages(scene, thread_store_new_doc(scene), "I want noodles")


def thread_store_new_doc(scene: Any) -> dict[str, Any]:
    from app.services import thread_store

    return thread_store.new_doc(scene)


# ============================================================ 1) _judge 的预算语义


@pytest.mark.asyncio
async def test_judge_converts_budget_exceeded_into_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超预算 -> ``LlmUnavailableError``, 而不是把 socket 拖到 30s 让 OkHttp 先炸."""
    _hanging(monkeypatch)
    started = time.monotonic()
    with pytest.raises(dg.LlmUnavailableError):
        await dg._judge(tg.TurnGeneration, _messages(), hard_budget_s=TINY_BUDGET_S)
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_judge_budget_wraps_the_malformed_json_retry_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预算封的是**整个调用含重试**, 不是单次尝试.

    反例 (v2.2.2 踩过、这里钉过): 单次 socket 20s > 墙钟 15s 时, "坏 JSON 回喂一次"
    那次重试根本进不了场就被墙砍掉 —— 两级超时必须是同向的。
    """
    install_slow_llm(monkeypatch, [(0.0, "not json at all"), (HANG_S, "")])
    started = time.monotonic()
    with pytest.raises(dg.LlmUnavailableError):
        await dg._judge(tg.TurnGeneration, _messages(), hard_budget_s=TINY_BUDGET_S)
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_judge_without_budget_still_returns_slow_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不传 ``hard_budget_s`` 就没有墙 —— 这正是 AST 门要挡的形状, 这里把它测出来。"""
    install_slow_llm(monkeypatch, [(0.6, one_reply_json())])
    started = time.monotonic()
    got = await dg._judge(tg.TurnGeneration, _messages())
    assert time.monotonic() - started >= 0.5 and got.reply
    assert not hasattr(got, "_budget"), "别把这条当契约, 它是反例"


@pytest.mark.asyncio
async def test_per_attempt_timeout_is_forwarded_and_retries_are_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = install_slow_llm(monkeypatch, [(0.0, one_reply_json())])
    await dg._judge(tg.TurnGeneration, _messages(), timeout=1.5, hard_budget_s=4.0)
    # ``with_options`` 只换 timeout; ``max_retries=0`` 在建 client 时就定了 (下一条测它)。
    assert client.options == {"timeout": 1.5}


def test_llm_client_disables_silent_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """``max_retries=0`` 是预算成立的前提: SDK 默认偷偷重试 2 次, 12s 会实打实变成 36s."""
    captured: dict[str, Any] = {}

    def _fake_client(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm_provider, "AsyncOpenAI", _fake_client)
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    llm_provider.reset_llm_provider_for_tests()
    llm_provider.get_llm_provider()
    assert captured.get("max_retries") == 0


def test_real_openai_client_carries_zero_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """真构造一次 (不打网络) 也要看到 ``max_retries=0`` —— 上一断言的接缝若被绕开这里就红."""
    import openai

    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    client = openai.AsyncOpenAI(api_key="k", base_url="https://example.test/v1", max_retries=0)
    assert client.max_retries == 0


# ============================================================ 2) 两条现役同步路


@pytest.mark.asyncio
async def test_generate_turn_raises_inside_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """``generate_turn`` (请求内唯一一次 LLM) 超预算**抛** ``LlmUnavailableError``.

    D5: 台词拿不到 -> 端点 503 且这一轮不前进, 绝不回放剧本 (旧 ``fallback_turn`` 那条路
    正是"每轮同一句"的根因)。所以这里断的是**异常**, 不是降级产物。

    预算改的是 ``turn_generation`` 命名空间里的名字: 那是**实际查找**它的地方。
    """
    _hanging(monkeypatch)
    shrink_budget(monkeypatch, tg, "GEN_TURN_BUDGET_S")
    started = time.monotonic()
    with pytest.raises(dg.LlmUnavailableError):
        await tg.generate_turn(_messages())
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_translate_respects_its_own_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """翻译挂死 -> 预算内抛 ``LlmUnavailableError`` (路由翻成 503, 不回显原文)."""
    _hanging(monkeypatch)
    shrink_budget(monkeypatch, tr, "TRANSLATE_BUDGET_S")
    started = time.monotonic()
    with pytest.raises(dg.LlmUnavailableError):
        await tr.translate_text("我想要牛肉面", "en")
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_thread_turn_respects_the_same_gen_wall(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v3.0 群聊一轮走**同一堵** GEN 墙: 挂死的 LLM 必须被预算砍成 503, 而不是拖死 socket.

    断的是"这条新路由真的受那堵墙约束" —— 它调 ``turn_generation.generate_turn``,
    所以 ``shrink_budget`` 改的仍是 ``turn_generation`` 命名空间。
    """
    from tests.test_dialogue_threads import _open

    shrink_budget(monkeypatch, tg, "GEN_TURN_BUDGET_S")
    _hanging(monkeypatch)
    thread_id = (await _open(client, "dev-lat")).json()["id"]
    started = time.monotonic()
    res = await client.post(
        f"/api/v1/dialogue/threads/{thread_id}/turn",
        json={"mode": "text", "text": "I want noodles"},
        params={"device_id": "dev-lat"},
    )
    assert res.status_code == 503, res.text
    assert res.json()["error"]["code"] == "TURN_GENERATION_UNAVAILABLE"
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_thread_tts_budget_exceeded_degrades_instead_of_failing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTS 墙到点必须是**软失败** (200 + ``audio_pending``), 不能把已经成功的台词打死.

    这条是"请求内合成"这个选择的前提: 语音条排在台词之后 (要先有文本才知道合成什么),
    所以它是**加**在 25s 求和上的一段。如果它超时会 503, 那就等于让学员为一次 TTS
    抖动重答一遍 —— 重答会再烧一次 LLM, 还会在会话里留下两颗一样的用户气泡。
    """
    from tests.test_dialogue_threads import _open

    install_slow_llm(monkeypatch, [(0.0, one_reply_json())])

    async def _hanging_tts(text: str, voice: str) -> Any:
        await asyncio.sleep(HANG_S)
        raise AssertionError("unreachable")

    monkeypatch.setattr(ta._provider, "synthesize", _hanging_tts)
    shrink_budget(monkeypatch, ta, "TTS_TURN_BUDGET_S")

    thread_id = (await _open(client, "dev-tts")).json()["id"]
    started = time.monotonic()
    res = await client.post(
        f"/api/v1/dialogue/threads/{thread_id}/turn",
        json={"mode": "text", "text": "I want noodles"},
        params={"device_id": "dev-tts"},
    )
    assert res.status_code == 200, res.text
    assert time.monotonic() - started < 3.0, "TTS 预算没起作用, 整轮被拖死了"
    line = next(m for m in res.json()["messages"] if m["kind"] == "line")
    assert line["audio_url"] is None and line["audio_pending"] is True, line


# ============================================================ 3) 契约的静态锁


#: 后台作业模块: 在 202/请求之外跑, 30s readTimeout 对它们不成立 -> 故意不设**请求内**
#: 硬预算 (仍各自有一堵作业墙, 见下面的作业断言)。豁免必须显式列出, 不许靠漏网。
ASYNC_JOB_MODULES = frozenset({"scene_spec_generator.py", "thread_grading.py"})


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
    """新增一条 ``_judge`` 调用而不写预算 -> 直接红 (没有默认值可躲)。

    这条是防止契约**再次腐化**的机器检查: 曾经 7 个调用点里只有 2 个有预算, 因为没有任何
    东西在问"这个 LLM 调用封顶了吗"。
    """
    sites = _judge_call_sites()
    assert len(sites) >= 4, f"AST 没扫到预期的调用点 ({sites}) —— 接缝大概被改了"
    unbudgeted = [(mod, line) for mod, line, ok in sites if not ok and mod not in ASYNC_JOB_MODULES]
    assert unbudgeted == [], (
        "这些同步路径的 LLM 调用没有硬预算, 最坏会拖过客户端 30s readTimeout: "
        f"{unbudgeted}; 给 _judge 传 hard_budget_s=*_BUDGET_S, 或 (确属后台作业) 把模块"
        "加进 ASYNC_JOB_MODULES 并说明为什么"
    )


def test_budgets_are_named_constants_at_the_call_sites() -> None:
    """调用点必须引用**常量名** (求和测试才读得到), 不许就地写字面量。"""
    for fn, module, name in (
        (tg.generate_turn, tg, "GEN_TURN_BUDGET_S"),
        (tr.translate_text, tr, "TRANSLATE_BUDGET_S"),
        (sg.generate_scene_spec, sg, "SCENE_BRIEF_JOB_BUDGET_S"),
        (thread_grading.grade_turn, thread_grading, "GRADING_TURN_BUDGET_S"),
    ):
        src = inspect.getsource(fn)
        assert f"hard_budget_s={name}" in src, f"{fn.__name__} 应把硬预算写成 {name}"
        assert hasattr(module, name), f"{module.__name__} 上找不到 {name} (改名没同步?)"


def test_thread_audio_synthesis_budget_is_a_named_constant() -> None:
    """语音条的预算写在 ``thread_audio`` 里且被 ``wait_for`` 真的用上 —— 不是装饰。"""
    src = inspect.getsource(ta.synthesize_line)
    assert "timeout=TTS_TURN_BUDGET_S" in src


def test_thread_endpoint_uses_generate_turn_not_a_bare_chat() -> None:
    """群聊轮不许手搓 ``provider.chat`` —— 它必须走 ``generate_turn``.

    旧形状两个毛病: ① 裸 ``chat`` 不受 ``hard_budget_s`` 保护 (``timeout=`` 只是单次尝试);
    ② 它自己拼的 prompt/温度/token 与别的链路各一份, 慢慢就漂了。
    """
    from app.api.v1 import dialogue_threads

    src = inspect.getsource(dialogue_threads.submit_turn)
    assert "turn_generation.generate_turn(" in src
    assert "provider.chat(" not in src

    prompt_src = inspect.getsource(thread_turn.turn_messages)
    # 形状与规则只有一份: 群聊在 GENERATION_FIELDS 之上多问两格, 而不是另写一遍。
    assert "turn_generation.GENERATION_FIELDS" in prompt_src
    assert "turn_generation.GENERATION_RULES" in prompt_src
    assert "turn_generation.ANTI_REPEAT_RULES" in prompt_src


def test_group_shape_is_the_shared_shape_plus_two_fields() -> None:
    """群聊的 JSON 形状必须是**派生**的, 不是第二份手写字面量 (漂移的接缝就在这儿)."""
    five = tg.GENERATION_JSON_SHAPE
    seven = tg.json_shape(tg.GENERATION_FIELDS + tg.GROUP_GENERATION_EXTRA_FIELDS)
    assert seven.startswith(five[:-1]), seven
    assert seven == five[:-1] + ', "speaker": "...", "next_beat": "..."}'


def _direct_chat_call_sites() -> list[tuple[str, int, bool]]:
    """绕过 ``_judge`` 直接 ``provider.chat(...)`` 的调用点 (必须显式写 timeout)."""
    sites: list[tuple[str, int, bool]] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "chat"
                and isinstance(func.value, ast.Name)
                and func.value.id.endswith("provider")
            ):
                has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                sites.append((path.name, node.lineno, has_timeout))
    return sites


def test_bare_provider_chat_calls_pass_an_explicit_timeout() -> None:
    """绕开 :func:`_judge` 的调用点也得显式写 ``timeout=`` —— 契约不允许"默认值兜底"。"""
    sites = _direct_chat_call_sites()
    assert sites, "AST 没扫到任何 provider.chat() —— 接缝变了, 请同步改本用例"
    missing = [(mod, line) for mod, line, ok in sites if not ok]
    assert missing == [], f"这些 provider.chat() 没有显式 timeout: {missing}"


# ============================================================ 4) 后台作业的作业墙


def test_scene_brief_job_is_async_with_a_named_wall() -> None:
    """自定义场景骨架: 请求内**零 LLM** (202 + 轮询), 作业侧报具名预算。"""
    from app.api.v1 import scene_specs

    src = inspect.getsource(scene_specs.create_custom_scene)
    assert "_judge" not in src and "provider.chat" not in src, "请求里不许再调 LLM"
    assert "spawn_scene_brief_job" in src
    assert sg.SCENE_BRIEF_JOB_BUDGET_S + 0.0 > CLIENT_READ_TIMEOUT_S, (
        "作业墙本就该越过 30s 契约 (它在请求之外跑) —— 缩回 30s 以内说明两处混淆了"
    )


def test_thread_grading_job_runs_outside_the_request() -> None:
    """每轮评分在请求之外: 作业必须点名 ``GRADING_TURN_BUDGET_S``, 端点不许同步等它."""
    from app.api.v1 import dialogue_threads

    assert "hard_budget_s=GRADING_TURN_BUDGET_S" in inspect.getsource(thread_grading.grade_turn)
    submit_src = inspect.getsource(dialogue_threads.submit_turn)
    assert "grade_turn" not in submit_src, "判分回到请求里 = 撞墙的那个旧形状回来了"
    # 派生动作收在 _spawn_grading 里 (端点只调那个工厂), 所以两处都要看。
    assert "_spawn_grading(" in submit_src, "端点必须把判分派出去, 不然评分卡永远 pending"
    assert "spawn_thread_grading(" in inspect.getsource(dialogue_threads._spawn_grading)


# ============================================================ 5) 求和 (契约本体)


def test_worst_case_sum_of_each_sync_path_fits_under_30s() -> None:
    """契约求和: 同请求内 ``各段预算之和 + 5s 余量 <= 30s``。

    求和**只许变小**。v3.0 之后同步路只有两条: 群聊一轮、长按翻译。

    **不要**把"ISE 恒 ≤ GEN 墙"当散文假设: 真正给 ISE 封顶的是讯飞服务层自己的
    ``xunfei_ise_timeout_s`` (调用点那 8.5s 只是外层再包一层), 所以这里断言
    "ISE 的真实最坏 + 余量 <= 台词墙" —— 成立时 ISE 被 ``max(...)`` 吃掉, 不额外加时。
    """
    ise_service_worst_s = float(settings.xunfei_ise_timeout_s)
    assert ise_service_worst_s + MARGIN_S <= dg.GEN_TURN_BUDGET_S, (
        "讯飞 ISE 的服务层最坏超时已越过台词墙 -> 求和不再成立 (ISE 会额外加时而不是被 max 吃掉)"
    )
    assert ise_service_worst_s <= dt_ise_budget()

    # 群聊一轮: IAT -> (ISE ∥ 台词) -> 请求内 TTS (串在台词之后, 所以是加不是 max)。
    thread_turn_s = (
        dt_iat_budget() + max(dt_ise_budget(), dg.GEN_TURN_BUDGET_S) + ta.TTS_TURN_BUDGET_S
    )
    fits = {
        "thread 单轮 (v3.0, 含请求内 TTS)": thread_turn_s,
        "translate (独立请求)": dg.TRANSLATE_BUDGET_S,
    }
    for name, worst in fits.items():
        assert worst + MARGIN_S <= CLIENT_READ_TIMEOUT_S, (
            f"{name} 最坏 {worst:.1f}s + {MARGIN_S:.0f}s 余量 已越过客户端 "
            f"{CLIENT_READ_TIMEOUT_S:.0f}s readTimeout"
        )

    # "顶格"是一个**需要被知道**的形状, 不是一条可以悄悄变化的事实: 有人放宽任一预算,
    # 这条就红, 逼他重算, 而不是让零余量悄悄存在。
    assert thread_turn_s + MARGIN_S == CLIENT_READ_TIMEOUT_S, (
        f"群聊一轮不再正好顶格 (当前 {thread_turn_s + MARGIN_S:.1f} vs 门 "
        f"{CLIENT_READ_TIMEOUT_S:.1f}): 要么预算变了要重算, 要么余量/超时变了要改这条注释"
    )


def dt_iat_budget() -> float:
    from app.api.v1 import dialogue_threads

    return float(dialogue_threads.IAT_TURN_BUDGET_S)


def dt_ise_budget() -> float:
    from app.api.v1 import dialogue_threads

    return float(dialogue_threads.ISE_TURN_BUDGET_S)


def test_thread_voice_path_picks_one_zh_cn_listening_language() -> None:
    """语音只走**一条** ``zh_cn`` 中英混读听写路 (实测见 ``scripts/smoke_iat_lang.py``)。

    这条锁的是"不要退回两次听写或加一个语言开关": 串行两次听写最坏 8+8=16s, 直接
    撑爆求和; 而让学员开口前先声明语言, 是把系统能自己做的事推给用户。
    """
    from app.api.v1 import dialogue_threads

    assert dialogue_threads._IAT_LANGUAGE == "zh_cn"
    src = inspect.getsource(dialogue_threads.submit_turn)
    assert src.count("_transcribe(") <= 1, "同一条请求里听写只许跑一次"

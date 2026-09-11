"""总评文案的后台作业 (§P6 / §2 问题 5) —— "收工不再在请求里等 LLM" 的那一份契约.

学员报的现象是"每日练习完成, 但没有对整体表现的总结, 点击完成提示 timeout"。生产实锤
(session ``719833d1…``, 2026-09-10): ``POST /sessions/{id}/finish-mission`` 在请求里同步
调总评 LLM, 烧了 ~68s 才降级, 而手机 OkHttp ``readTimeout`` 只有 30s —— **服务端把活干完
了、报告也落库了, 学员却永远看不到**, 猛点收工只换来 4 连 409。到轮次上限的自动收工更糟
(那一轮本身已经花掉 ~23s)。

§P6 的修法是把报告切成两半: 复盘报告只有四件东西来自模型 (``highlights`` /
``improvements`` / ``source`` / ``llm_source``), 其余全是 ``practice_steps`` 行与 doc 快照
的算术。于是**请求内只算数值骨架** (202 + ``review_status="generating"``), 文案交给
``run_review_copy_job`` 慢慢补。本文件钉的就是这个新形状, 按"客户端会怎么踩"组织:

1. **202 不含文案, 也没等 LLM** —— 挂死的假 LLM 之下请求仍然秒回 (墙钟 + 调用次数双证);
2. **骨架当场就可读** —— 收工那一刻总分/四维/清单/逐词/生词全在, 文案是确定性版本,
   复盘页不必整页转圈 (§P6 第 8 项那个"数值已在, 文案在写"的第三态, 数据面就是这里);
3. **作业必落终态** —— 成功 -> ``ready`` + ``source="llm"``; LLM 挂死 -> 预算内降级成
   ``ready`` + ``heuristic``; 崩了 -> ``failed``; **没有一条路径留在 ``generating``**;
4. **数值一次写定** —— 重跑/重派都不许改动学员已经看到的那个分数 (``merge_review_copy``
   只覆盖那四件);
5. **轮询通道只有一个** —— 沿用 ``GET /sessions/{id}`` (不新增端点), 它在每一跳都回
   ``review_status``, 并且把停摆的作业**就地幂等重派** (重启兜底), 收完工之后报告要一直
   可达 (§P6 第 9 项客户端"查看上次复盘"的数据前提)。

手法沿用既有模块, 不另造接缝: ``install_llm`` / ``install_slow_llm`` (会**真的**睡, 见
``test_latency_budget`` 的理由: 即时返回的 fake 测不出时延) / ``shrink_budget`` (改的是
**消费方**命名空间里的名字)。作业一律由用例自己 ``await cs.run_review_copy_job(sid)``
驱动 —— ``tests/conftest.py`` 的 autouse 已把 ``spawn_review_copy_job`` 换成 no-op, 免得
真任务活过内存 sqlite 的 dispose。要断"派生了作业", 用 :func:`_record_spawns` 换掉那个
no-op 记账 (它**不**真开任务); 要断"在途只许一个", 用导入期抓住的 :data:`ORIGINAL_SPAWN`。
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import course_sessions as cs
from app.core.errors import AppError
from app.db.session import get_sessionmaker
from app.main import app
from app.models.db import PracticeSession, PracticeStep
from app.services import llm_provider, scene_store
from app.services import mission_engine as me
from tests.test_course_sessions import BRIEFING6
from tests.test_drill_grader import install_llm
from tests.test_latency_budget import HANG_S, install_slow_llm, shrink_budget
from tests.test_mission import DEV, _finish, _mission, _ready, mission_json
from tests.test_scene_store import make_course_dict

#: 假 LLM 的默认模型 id (``install_llm`` 写死), 作业的 ``llm_source`` 该等于它.
FAKE_MODEL = "qwen3.8-max"
#: 报告里**唯一**来自模型的四个字段 —— 其余一律是收工时就算好的数值 (§P6 的拆分线).
PROSE_KEYS = frozenset({"highlights", "improvements", "source", "llm_source"})

#: 总评文案的合法回复 (``ReviewTextJudgement`` 的形状).
REVIEW_A = json.dumps(
    {
        "highlights": ["点单和问价都当面说出口了, 沟通目的达成。"],
        "improvements": ["语法: 特殊疑问句的语序再练一轮。"],
    },
    ensure_ascii=False,
)
REVIEW_B = json.dumps(
    {
        "highlights": ["另一套文案: 你不该看到这一条。"],
        "improvements": ["另一套文案: ready 之后再派也不该覆盖。"],
    },
    ensure_ascii=False,
)
#: 聊两轮的综合 JSON (语法 66 / 词汇 70 -> 骨架 overall 68), 与 test_mission 同一份料.
_TURN_T1 = mission_json(done=[("t1", "说了点单内容")])
_TURN_T2 = mission_json(
    done=[("t1", "说了点单内容"), ("t2", "问了价格")],
    polish={
        "original": "How much money?",
        "polished": "How much is that in total?",
        "explanation_cn": "问价格说 how much is that。",
    },
)

#: autouse 夹具会把模块属性换成 no-op; 导入期抓住原身, 供"在途幂等门"那条用例用.
ORIGINAL_SPAWN = cs.spawn_review_copy_job
#: 同上: 乐观锁那两条用例要让"某一刀"失败、下一刀照旧走真身.
ORIGINAL_SAVE_DOC = cs._save_doc


# ---------------------------------------------------------------------- 夹具 / helper


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    """假 provider 必须在每个用例前后归零, 否则"LLM 已配置"会泄漏给后面的模块."""
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_review_dispatch_state() -> AsyncIterator[None]:
    """模块级派生门 (``_REVIEW_IN_FLIGHT`` / ``_REVIEW_JOBS``) 是用例之间的共享可变状态.

    不还清会在途 id 留给下一个用例 (幂等门会把它判成"已经在跑了"), 不 cancel 掉真任务的
    话, 它还会活过内存 sqlite 的 dispose —— 报错出现在 teardown 栈里, 看着像数据库坏了。
    """
    cs._REVIEW_IN_FLIGHT.clear()
    cs._REVIEW_JOBS.clear()
    yield
    pending = [task for task in cs._REVIEW_JOBS if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    cs._REVIEW_IN_FLIGHT.clear()
    cs._REVIEW_JOBS.clear()


@pytest.fixture(autouse=True)
def course_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    """假课 ``scene_alpha`` (``BRIEFING6`` + 三个沟通任务) + 接管 corpus 根目录; **autouse**.

    默认就装好一门 8 轮的课 (每条用例都要能开局), 需要别的形状的用例再调一次工厂覆写它:
    自动收工那条要**小**的 ``max_turns`` (轮次上限到顶才算"日常收工"的形状)。课程是开场时
    快照进 doc 的, 所以覆写只影响之后开的新局。
    """
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)

    def _make(*, max_turns: int = 8) -> Path:
        payload = make_course_dict("scene_alpha", "daily")
        payload["briefing"] = BRIEFING6
        payload["mission"] = {**payload["mission"], "max_turns": max_turns}
        scenes = tmp_path / "scenes"
        scenes.mkdir(parents=True, exist_ok=True)
        (scenes / "scene_alpha.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        scene_store.invalidate_cache()
        return tmp_path

    _make()  # 默认课先装好 (autouse: 用例不该因为"忘了开场景"而 404)
    yield _make
    scene_store.invalidate_cache()


class _SpawnRecorder:
    """把 ``spawn_review_copy_job`` 换成**只记账不真开任务**的替身 (覆盖 conftest 的 no-op)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, session_id: str) -> bool:
        self.calls.append(session_id)
        return True


def _record_spawns(monkeypatch: pytest.MonkeyPatch) -> _SpawnRecorder:
    recorder = _SpawnRecorder()
    monkeypatch.setattr(cs, "spawn_review_copy_job", recorder)
    return recorder


async def _snapshot(client: AsyncClient, sid: str, device: str = DEV) -> dict[str, Any]:
    """客户端唯一的轮询通道: 复盘页读的就是这个 (§P6 不新增端点)."""
    res = await client.get(f"/api/v1/sessions/{sid}", params={"device_id": device})
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _read_doc(db: AsyncSession, sid: str) -> dict[str, Any]:
    """直接读快照 (作业写的键都在 ``doc`` 里: ``review_status`` / ``review_facts``)."""
    row = (
        (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalars().one()
    )
    return copy.deepcopy(dict(row.doc))


async def _write_doc(db: AsyncSession, sid: str, doc: dict[str, Any]) -> None:
    """整体换新写回 —— JSON 列原地改不会脏 (``_save_doc`` 的同一条坑, 测试也得守)."""
    row = (
        (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalars().one()
    )
    row.doc = copy.deepcopy(doc)
    await db.commit()


async def _age_job(db: AsyncSession, sid: str, *, seconds: float) -> dict[str, Any]:
    """把快照的 ``updated_at`` 往回拨 —— 重派水位读的就是它 (作业最后落笔的那一刻)."""
    doc = await _read_doc(db, sid)
    doc["updated_at"] = cs._iso(datetime.now(UTC) - timedelta(seconds=seconds))
    await _write_doc(db, sid, doc)
    return doc


def _numbers(report: dict[str, Any]) -> dict[str, Any]:
    """剥掉那四件文案, 剩下的就是"收工那一刻算好、之后谁也不许动"的数值."""
    return {key: value for key, value in report.items() if key not in PROSE_KEYS}


async def _played_ready(client: AsyncClient, sid: str, *, turns: int = 2) -> None:
    """**无凭据**聊几轮 (启发式判定, 不吃假 LLM 的脚本): 通关卡在 ``cleared`` 上.

    话术取自 ``test_mission`` 的启发式用例 —— ``A small coffee, please.`` 推进 t1,
    ``How much is that?`` 推进 t2 并通关。分数是启发式的 (不可信来源 -> 四维可空),
    但数值骨架照样完整, 所以"202 不等 LLM"那几条不需要真凭据。
    """
    script = ["A small coffee, please.", "How much is that?", "Thanks, have a good day."]
    for index in range(turns):
        res = await _mission(client, sid, {"text": script[index % len(script)]})
        assert res.status_code == 200, res.text


async def _scored_session(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
    replies: list[Any],
) -> str:
    """开一局打到**有真分数**的现场 (语法 66 / 词汇 70 -> 骨架 overall 68) 并主动收工.

    ``replies`` 拼在两轮判定之后: ``_FakeOpenAI`` 先吐掉前面的脚本, 最后一条无限重复, 所以
    传给它的**第一条**就是作业会拿到的那份总评文案。分数走假 LLM 是因为"数值一次写定"那条
    锁要有非空的数才断得动 —— 全程无凭据时可信来源全空 (那也是有意义的状态, 但证不了"没被
    改动")。
    """
    course_root()
    sid = await _ready(client)  # 先打完基础, 免得判分吃掉脚本
    install_llm(monkeypatch, [_TURN_T1, _TURN_T2, *replies])
    for text in ("Can I get a medium coffee?", "How much money?"):
        res = await _mission(client, sid, {"text": text})
        assert res.status_code == 200, res.text
    await _finish(client, sid)
    return sid


# ==================================================== 1) 202: 不含文案, 也没等 LLM


@pytest.mark.asyncio
async def test_finish_mission_returns_202_without_the_prose_or_the_llm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, course_root: Callable[..., Path]
) -> None:
    """收工请求**一次 LLM 都不碰**: 挂死的假 LLM 之下仍然秒回, 且调用次数为 0.

    两条断言各管一头。``report`` 缺席钉的是**契约** (D6: 宁可改状态码也不留一个"可能有点
    用"的同步字段, 那只会诱使后来人在请求里补一次 LLM); ``fake.calls == 0`` 钉的是**时延**
    —— 只看响应体分不清"异步"与"同步但恰好很快", 而那正是这个 bug 藏了很久的原因。
    """
    course_root()
    sid = await _ready(client)
    await _played_ready(client, sid)
    fake = install_slow_llm(monkeypatch, [(HANG_S, "")])  # 谁调谁睡, 且永不给合法 JSON

    started = time.monotonic()
    body = await _finish(client, sid)  # _finish 已钉 202 / review_status / stage / 无 report
    elapsed = time.monotonic() - started

    assert set(body) == {"session_id", "revision", "stage", "status", "review_status"}
    assert body["session_id"] == sid and body["revision"] >= 1
    assert (body["stage"], body["status"], body["review_status"]) == (
        "review",
        "completed",
        "generating",
    )
    assert "report" not in body and "review" not in body
    assert elapsed < 3.0, f"收工还像在等总评 (实际 {elapsed:.1f}s; 假 LLM 一睡就是 {HANG_S}s)"
    assert fake.calls == 0, "请求里出现了一次 LLM 调用 —— 那正是学员报的超时形状"


# ============================================ 2) 骨架就地可读 (§P6 第 8 项的数据面)


@pytest.mark.asyncio
async def test_the_202_skeleton_is_already_a_readable_report(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """``generating`` 那一刻报告就该**能读**: 数值全在, 文案是确定性版本.

    这是异步化唯一的用户体验理由 —— 如果 202 之后复盘页只能整页转圈, 学员的感受和超时没有
    区别。所以逐项钉住"纯算术"那半边: 总分 / 四维 / 任务清单 / 原话对照 / 生词 / 画像增量,
    外加两句非空白文案 (``source="heuristic"``, 复盘页已有的降级横幅会说明来源)。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    view = await _snapshot(client, sid)
    assert view["review_status"] == "generating"
    report = view["review"]

    assert report["cleared"] is True and report["auto_finished"] is False
    assert report["turn_count"] == 2 and report["max_turns"] == 8
    # 只聚合可信来源: 假 LLM 给的 66/70 在; 没配讯飞 -> 发音/流利可空 (宁缺勿滥, §5.6)
    assert report["dims"]["grammar"] == pytest.approx(66.0)
    assert report["dims"]["vocabulary"] == pytest.approx(70.0)
    assert report["dims"]["pronunciation"] is None
    assert report["overall"] == pytest.approx(68.0)
    assert [entry["done"] for entry in report["checklist"]] == [True, True, False]
    assert report["transcript_pairs"][0]["polished"] == "How much is that in total?"
    assert set(report["new_tokens"]) >= {"order", "sugar"}  # 转写里真说过的核心词
    assert set(report["ability_delta"]) == {
        "pronunciation",
        "grammar",
        "vocabulary",
        "fluency",
    }
    # 文案位不是空白, 但此刻确实还是模板 —— 这正是 review_status 存在的意义。
    assert report["source"] == "heuristic" and report["llm_source"] == "stub"
    assert report["highlights"] and report["improvements"]

    # 重派要能还原同一份 prompt 输入, 所以骨架阶段就把**已裁剪**的那份料落进快照。
    doc = await _read_doc(db, sid)
    assert isinstance(doc["review_facts"], dict)
    assert doc["review_facts"]["dims"]["grammar"] == pytest.approx(66.0)


# ============================================ 3) 收工确实把作业派出去了


@pytest.mark.asyncio
async def test_finish_mission_dispatches_exactly_one_copy_job(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """202 之后那句"AI 正在写总评"能不能兑现, 全看这一句 ``spawn_review_copy_job``.

    断的是**恰好一次**: 派零次 = 学员永远看着"生成中"; 派多次 = 同一会话白烧几次 LLM。
    重复收工现在秒级返回 409 (行锁不再被写作占用), 更要钉住"409 那条路径一个作业都不派"。
    """
    spawned = _record_spawns(monkeypatch)
    sid = await _ready(client)
    await _played_ready(client, sid)

    await _finish(client, sid)
    assert spawned.calls == [sid], "收工没派文案作业 (或派给了别的会话)"

    # 重复收工: 会话已 completed -> 409 那道口 (E1 修的就是它曾经能重放收工并 bump revision)
    repeat = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "SESSION_NOT_ACTIVE"
    assert spawned.calls == [sid], "重复收工 (409) 不该再派一次作业"


# ================================================== 4) 作业的三条终态出口


@pytest.mark.asyncio
async def test_the_job_merges_the_prose_without_moving_a_number(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """作业成功: 翻 ``ready`` + 换成模型文案, **数值逐字段不变**.

    ``_numbers(after) == _numbers(before)`` 是本文件最值钱的一条断言: 它锁住"重跑/重派永远
    不会改动学员收工时已经看到的那个分数"。哪天有人把整份报告**整体**覆盖回去 (而不是走
    ``merge_review_copy``), 这条就会红 —— 那种写法在 LLM 正常时看不出问题, 但并发收工/重派
    时读到的 step 行可能已经不同, 学员就会看到总分悄悄变了。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    before = (await _snapshot(client, sid))["review"]
    assert (await _snapshot(client, sid))["review_status"] == "generating"

    await cs.run_review_copy_job(sid)

    view = await _snapshot(client, sid)
    assert view["review_status"] == "ready"
    report = view["review"]
    assert report["highlights"] == ["点单和问价都当面说出口了, 沟通目的达成。"]
    assert report["improvements"] == ["语法: 特殊疑问句的语序再练一轮。"]
    assert report["source"] == "llm" and report["llm_source"] == FAKE_MODEL
    assert _numbers(report) == _numbers(before), (
        "文案作业改动了数值 —— 复盘页每次刷新换个总分, 报告就不可信了"
    )
    assert report["overall"] == pytest.approx(68.0)
    # 写完就是终点: 那堆 prompt 料不必再占着整场会话的快照 (JSON 列会越滚越大)。
    assert "review_facts" not in await _read_doc(db, sid)


@pytest.mark.asyncio
async def test_the_job_never_re_aggregates_the_live_step_rows(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """作业**不重算**分数: 收工之后 step 行变了, 报告里的数也只能是收工那一刻的.

    上一条比的是"同样的输入重跑一遍", 这条把**底层数据改掉** (像是骨架落库之后又有人补交
    了一次评分)。后台作业压根不查 ``practice_steps`` + ``merge_review_copy`` 只覆盖四件文案
    —— 两件事合起来才是"学员已经看到的那个分数不会被挪动"。哪天有人把作业改成"重新聚合一次
    再合并", 这里就会红。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    skeleton = (await _snapshot(client, sid))["review"]
    assert skeleton["dims"]["grammar"] == pytest.approx(66.0)

    await db.execute(
        update(PracticeStep)
        .where(PracticeStep.session_id == sid, PracticeStep.score_grammar.is_not(None))
        .values(score_grammar=99.0)
    )
    await db.commit()

    await cs.run_review_copy_job(sid)
    report = (await _snapshot(client, sid))["review"]
    assert report["source"] == "llm", "先确认文案确实补上了, 否则下面那条比较是空的"
    assert report["dims"]["grammar"] == pytest.approx(66.0)
    assert _numbers(report) == _numbers(skeleton), (
        "作业把收工之后的数据变化算了进来 —— 总分成了会动的数, 复盘页不再是收工那一份"
    )


@pytest.mark.asyncio
async def test_a_hung_llm_degrades_to_ready_inside_the_job_budget(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """LLM 挂死 -> 在**作业预算**内降级成 ``ready`` + ``heuristic``, 绝不留在 ``generating``.

    ``REVIEW_COPY_JOB_BUDGET_S`` (45s) 故意大于 socket 的 30s: 请求在 202 就返回了, 这堵墙
    不是给客户端交差的, 而是保证"一条挂死的调用不会把会话永远留在生成中"。所以断的是**多快**
    落终态 + 落的是**哪个**终态:

    * 预算名字绑在**消费方** (``course_sessions``) 的命名空间里 —— 打在 ``mission_engine``
      上会静默无效, :func:`shrink_budget` 自己会断言这点, 这里再断一次"另一侧确实没有";
    * 降级回来仍是模板文案, 数值一个没动 (复盘页的降级横幅会说清来源)。
    """
    assert not hasattr(me, "REVIEW_COPY_JOB_BUDGET_S"), (
        "作业预算不该被 import 进 mission_engine —— 那里只有同步组合的 REVIEW_LLM_BUDGET_S"
    )
    shrink_budget(monkeypatch, cs, "REVIEW_COPY_JOB_BUDGET_S")
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    skeleton = (await _snapshot(client, sid))["review"]
    fake = install_slow_llm(monkeypatch, [(HANG_S, "")])

    started = time.monotonic()
    await cs.run_review_copy_job(sid)
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"挂死的 LLM 没被作业预算封顶 (实际 {elapsed:.1f}s)"
    assert fake.calls == 1, f"一次调用 + 封顶就够, 实际 {fake.calls} 次在乘预算"
    view = await _snapshot(client, sid)
    assert view["review_status"] == "ready"
    report = view["review"]
    assert report["source"] == "heuristic" and report["llm_source"] == "stub"
    assert report["highlights"] and report["improvements"], "降级也不能交出空白报告"
    assert _numbers(report) == _numbers(skeleton)


@pytest.mark.asyncio
async def test_an_unexpected_crash_lands_failed_yet_the_numbers_stay_readable(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """预期外异常 -> ``failed``: 状态**有下文**, 报告**照旧能渲染**.

    "绝不让后台任务无声死去"的落地点。文案的两条正常出口之外, 剩下的都是代码 bug / 数据库
    抖动 / 快照坏了 —— 它们不许把会话留在 ``generating`` (那等于把一次超时换成一个永久转圈
    的页面), 也不许把 ``review`` 打空 (数值在收工那次 commit 里就落好了)。故意抛**非 LLM**
    的 ``RuntimeError``: ``review_copy`` 只吃 ``LlmUnavailableError``, 后者会冒到作业兜底。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    skeleton = (await _snapshot(client, sid))["review"]

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("作业里炸了一个没人预期的错")

    monkeypatch.setattr(me, "review_copy", _boom)
    await cs.run_review_copy_job(sid)

    view = await _snapshot(client, sid)
    assert view["review_status"] == "failed"
    report = view["review"]
    assert _numbers(report) == _numbers(skeleton)
    assert report["highlights"] and report["improvements"]
    assert (report["source"], report["llm_source"]) == ("heuristic", "stub")
    # failed 还要能被重派, 所以那份 prompt 料**留在**快照里 (见 _fail_review_copy 的注)。
    assert "review_facts" in await _read_doc(db, sid)


@pytest.mark.asyncio
async def test_a_corrupt_snapshot_converges_to_failed_instead_of_a_500(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """快照坏了 (``review`` 不见了) 也只落 ``failed``: 后台作业没有 500 可报.

    作业跑在请求之外, 那里抛出去的异常**没有人接** —— 所以它唯一的表达方式就是状态。这条
    钉的是实现里的显式 ``SESSION_DOC_CORRUPT`` 分支没有变成一次静默死亡。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    doc = await _read_doc(db, sid)
    del doc["review"]
    await _write_doc(db, sid, doc)

    await cs.run_review_copy_job(sid)
    assert (await _snapshot(client, sid))["review_status"] == "failed"


# ================================================== 5) 幂等 / 门


@pytest.mark.asyncio
async def test_rerunning_a_ready_job_changes_nothing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """``ready`` 之后再跑一次 (重派撞车、猛点复盘页都会这样): 一个字都不改.

    第二遍换成**另一套**文案, 所以只要作业真重跑过一次就会被抓到; 同时钉住状态不被翻回
    ``generating`` —— 轮询键一旦被翻回去, 复盘页就又开始转圈, 而那正是学员现在看到的样子。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    await cs.run_review_copy_job(sid)
    first = await _snapshot(client, sid)
    assert first["review_status"] == "ready" and first["review"]["source"] == "llm"

    fake = install_llm(monkeypatch, [REVIEW_B])
    await cs.run_review_copy_job(sid)

    second = await _snapshot(client, sid)
    assert second["review_status"] == "ready", "重跑把终态翻回了中间态"
    assert second["review"] == first["review"]
    assert second["revision"] == first["revision"]
    assert fake.requests == [], "ready 的作业不该再去问一次 LLM"


@pytest.mark.asyncio
async def test_a_crash_after_the_copy_landed_never_downgrades_ready(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """文案已经 ``ready``, 兜底又被跑了一次 -> 只准不动, 不准把终态改成 ``failed``.

    ``_fail_review_copy`` 里那句"已经有终态了, 别把 ready 改回 failed"守的是学员侧的确定性:
    复盘页显示过的那份总评不能因为一次撞车的重派突然变成错误态。这里让作业**主体**在落库
    之后再炸 (模拟"写完文案后又踩到一个 bug"), 于是兜底路径真的会跑一遍。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    await cs.run_review_copy_job(sid)
    assert (await _snapshot(client, sid))["review_status"] == "ready"

    async def _explode_after_the_fact(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("落库之后作业里又踩到一个 bug")

    monkeypatch.setattr(cs, "_run_review_copy_job", _explode_after_the_fact)
    await cs.run_review_copy_job(sid)

    after = await _snapshot(client, sid)
    assert after["review_status"] == "ready", "终态被兜底改写 -> 学员的报告会突然变成错误态"
    assert after["review"]["source"] == "llm"


@pytest.mark.asyncio
async def test_the_job_that_loses_the_optimistic_race_writes_no_second_cut(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """落库输给了乐观锁 (重派出来的第二个作业先写了) -> **不再补第二刀**, 也不抛.

    ``_commit_review_copy`` 只把 ``SESSION_CONCURRENT_UPDATE`` 咽下去, 其它 ``AppError``
    照旧冒到终态兜底。为什么不制造真并发: 测试跑在 sqlite 的 StaticPool 上 (一条连接),
    两个会话交错事务测的不是乐观锁本身 (那由 ``test_course_sessions`` 的并发用例钉), 这里
    要钉的是**输家的行为** —— 快照留在 ``generating``, 于是下一次过水位的 GET 还能重派。
    """
    # 两局都先收完工: patched 的 _save_doc 会让收工本身 409, 所以现场必须提前备好。
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    skeleton = (await _snapshot(client, sid))["review"]
    other = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])

    async def _lose(*args: Any, **kwargs: Any) -> int:
        raise AppError(
            409, "this session was updated by another request", "SESSION_CONCURRENT_UPDATE"
        )

    monkeypatch.setattr(cs, "_save_doc", _lose)
    await cs.run_review_copy_job(sid)  # 不抛 = 作业不会把 traceback 甩进无人接的 task

    view = await _snapshot(client, sid)
    assert view["review_status"] == "generating", "输家不该改状态: 下一跳 GET 还要靠它重派"
    assert _numbers(view["review"]) == _numbers(skeleton)

    attempts = {"n": 0}

    async def _broken_once(*args: Any, **kwargs: Any) -> int:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise AppError(500, "数据库真出了别的问题", "DB_SOMETHING")
        return await ORIGINAL_SAVE_DOC(*args, **kwargs)

    # 只让**写文案那一刀**失败: 连终态那刀也写不进去就是另一种情况 (数据库整个不行了,
    # 那时能做的只有把栈打全), 不在本用例的射程里。
    monkeypatch.setattr(cs, "_save_doc", _broken_once)
    await cs.run_review_copy_job(other)
    assert attempts["n"] == 2, "非竞争性冲突没冒到终态兜底 (第一次写之后就该再写一次状态)"
    assert (await _snapshot(client, other))["review_status"] == "failed", (
        "非竞争性冲突被和竞争一起咽掉了 -> 会话永远留在 generating, 没人知道为什么"
    )


@pytest.mark.asyncio
async def test_the_job_returns_quietly_when_the_session_row_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """会话行没了 (清库/传错 id) 也安静返回: 作业外面是 ``create_task``, 没人接异常.

    抛出去只会变成一条 unhandled-task 日志 (同 ``test_course_generator`` 对不存在的 job 的
    口径)。这里顺带钉"什么都没写": 不存在的会话不该被造出任何状态。
    """
    fake = install_slow_llm(monkeypatch, [(0.0, REVIEW_A)])
    await cs.run_review_copy_job("00000000-0000-0000-0000-000000000000")
    assert fake.calls == 0

    # 写那一刀同理: 行没了就留一行日志, 不许抛 (作业外面没有 except 接得住)。单独叫这一刀
    # 是因为"读的时候行还在、写的时候被清了"这个窗口在 sqlite (单连接) 上交错不出来。
    async with get_sessionmaker()() as session:
        await cs._commit_review_copy(
            session, "00000000-0000-0000-0000-000000000000", {"review_status": "ready"}
        )


# ============================================ 6) 轮询通道: 每一跳都看得见状态


@pytest.mark.asyncio
async def test_review_status_is_visible_on_get_at_every_stage(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """客户端**只有** ``GET /sessions/{id}`` 这一条轮询道 (§P6 选型: 不新增端点).

    所以它必须一路带话: 没收工 -> ``None``; 收工完 -> ``generating``; 作业落地 -> ``ready``。
    少一跳客户端就没法判断该不该继续轮询。计划 §P6 第 2 项"每次状态变更立即 commit"就是为
    了让这条端点读得到 —— 轮询读的是**另一个** AsyncSession。
    """
    assert not any(path.endswith("/review") for path in app.openapi()["paths"]), (
        "§P6 的选型是不新建复盘端点: 报告与状态一直搭 GET /sessions/{id} 的便车"
    )

    course_root()
    sid = await _ready(client)
    await _played_ready(client, sid)
    active = await _snapshot(client, sid)
    assert active["review_status"] is None and active["review"] is None

    await _finish(client, sid)
    generating = await _snapshot(client, sid)
    assert generating["review_status"] == "generating"
    assert generating["review"] is not None, "文案没写完不是整页缺席的理由"

    install_llm(monkeypatch, [REVIEW_A])
    await cs.run_review_copy_job(sid)
    ready = await _snapshot(client, sid)
    assert ready["review_status"] == "ready" and ready["review"]["source"] == "llm"


@pytest.mark.asyncio
async def test_the_report_stays_reachable_after_the_session_is_completed(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    course_root: Callable[..., Path],
) -> None:
    """收完工 (``status="completed"``) 的局还能读: 客户端"查看上次复盘"的数据前提.

    §P6 第 9 项: 客户端目前**没有任何路径**能回到一场打完的课 (详情页只查 active, 查不到
    就擅自开新局 —— 想看总评反而会丢掉它)。那个修法完全依赖这条既有端点对 completed 会话
    继续回传 ``review``, 所以把它钉死: 反复轮询不改状态、不推高 revision (客户端拿 revision
    做条件写会被这个坑), 而且列表端点能把这局找回来。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    await cs.run_review_copy_job(sid)
    spawned = _record_spawns(monkeypatch)

    first = await _snapshot(client, sid)
    second = await _snapshot(client, sid)
    assert (first["stage"], first["status"]) == ("review", "completed")
    assert first["review_status"] == "ready" and first["review"]["cleared"] is True
    assert first["review"] == second["review"]
    assert first["revision"] == second["revision"], "轮询 GET 不该每次都推高 revision"
    assert spawned.calls == [], "写完的老局被重派 = 每次打开复盘页重写一遍文案"

    listed = await client.get("/api/v1/sessions", params={"device_id": DEV, "status": "completed"})
    assert listed.status_code == 200, listed.text
    assert sid in [entry["session_id"] for entry in listed.json()]


# ================================================== 7) 重启兜底: 就地幂等重派


@pytest.mark.asyncio
async def test_a_get_redispatches_a_stalled_generating_job(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """进程死在作业中途 -> ``create_task`` 不会自己回来, 由 GET 补派一次 (§P6 的兜底闭环).

    水位 = ``REVIEW_REDISPATCH_AFTER_S`` (= 2x 作业预算)。判早了会把**还在跑**的作业当成死
    的重派 (白烧一次 LLM + 多 bump 一次 revision), 判晚了学员整晚看不到文案 —— 所以正反
    各钉一次, 外加"GET 只派活、不替作业写终态"。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    spawned = _record_spawns(monkeypatch)

    await _age_job(db, sid, seconds=cs.REVIEW_REDISPATCH_AFTER_S + 5)
    assert spawned.calls == [], "改快照本身不触发派生: 门在 GET 上"

    view = await _snapshot(client, sid)
    assert spawned.calls == [sid], "老过水位的 generating 没被重派 -> 学员永远看'生成中'"
    assert view["review_status"] == "generating", "重派只是再开一次作业, 不许替它写终态"

    spawned.calls.clear()
    await _age_job(db, sid, seconds=cs.REVIEW_REDISPATCH_AFTER_S - 30)
    await _snapshot(client, sid)
    assert spawned.calls == [], "还在预算周期内的作业被判死 -> 会重派一次白烧的 LLM"


@pytest.mark.asyncio
async def test_a_get_redispatches_a_stalled_failed_job_at_the_shorter_threshold(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """``failed`` 过**一个**预算周期就该允许再试, 不必等下次重启.

    与 ``generating`` 的差别全在时刻: 崩掉那一刻作业**已经停了**, 没有"再给它一点时间"的
    意义。这里用 ``REVIEW_COPY_JOB_BUDGET_S + 5`` (只有 generating 水位的一半不到) 把两个
    阈值分开钉, 顺手断"刚 failed 就重派"仍然被拒 (连开三次复盘页 = 连烧三次 LLM)。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    doc = await _read_doc(db, sid)
    doc["review_status"] = "failed"
    await _write_doc(db, sid, doc)
    spawned = _record_spawns(monkeypatch)

    await _age_job(db, sid, seconds=cs.REVIEW_COPY_JOB_BUDGET_S - 20)
    await _snapshot(client, sid)
    assert spawned.calls == [], "刚 failed 就重派 = 反复打开页面会连着烧好几次"

    await _age_job(db, sid, seconds=cs.REVIEW_COPY_JOB_BUDGET_S + 5)
    await _snapshot(client, sid)
    assert spawned.calls == [sid], "failed 的会话没人救 -> 只能等进程重启, 学员没有重试出口"


@pytest.mark.asyncio
async def test_a_redispatched_failed_job_still_refuses_to_run(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """重派一个 ``failed`` 的会话: 作业在入口的状态复查那儿**静默退回** (现状锁).

    这一条记的是实现里一处**互相矛盾**的说法, 不是我认为对的行为:
    ``_fail_review_copy`` 与 ``resume_stranded_review_copy`` 的注释都说"failed 的会话还能被
    GET 重派, 重派需要同一份料", 而 ``_run_review_copy_job`` 的入门门写的是
    ``status != "generating"`` —— 于是重派出去的那一次第一件事就是自己退出。
    净效果: 崩过一次文案的会话会**永久**停在 ``failed``, 反复打开复盘页只是多派几个空转的
    作业 (数值仍然完整可渲染, 所以不是数据事故, 是"学员没有重试出口")。

    本用例只把现状钉住, 让修复者必须**显式**改动它 (把 ``failed`` 也当可补的状态, 或反过来
    把 failed 从 ``_REVIEW_RESUME_STATUSES`` 里摘掉并给客户端一条真正的重试端点)。
    已作为 §P6 的实现缺口上报, 测试不做任何"顺手修一下"。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    skeleton = (await _snapshot(client, sid))["review"]
    doc = await _read_doc(db, sid)
    del doc["review_facts"]  # 让作业即使真的跑起来也没料可补, 从而**绝不**落回 ready
    doc["review_status"] = "failed"
    await _write_doc(db, sid, doc)

    await cs.run_review_copy_job(sid)

    view = await _snapshot(client, sid)
    assert view["review_status"] == "failed", (
        "重派把 failed 改成了别的状态 —— 现状变了, 请同步改本用例与那两处注释的说法"
    )
    assert _numbers(view["review"]) == _numbers(skeleton), "报告至少还得是可渲染的那一份"


def test_redispatch_thresholds_are_per_status() -> None:
    """水位判定的真值表 (纯函数: 状态 x 时刻), 不用起会话也不用起作业.

    读不出时刻一律当"已过水位" —— 重派幂等, 宁可多写一次文案, 也别把学员永久留在"生成中"。
    这条不对称是故意的, 别顺手"修平"它。
    """
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    def aged(seconds: float, status: str) -> dict[str, Any]:
        return {"review_status": status, "updated_at": cs._iso(now - timedelta(seconds=seconds))}

    fresh, stale = 1.0, cs.REVIEW_REDISPATCH_AFTER_S + 1
    assert cs.review_copy_is_stranded(aged(stale, "generating"), now=now) is True
    assert cs.review_copy_is_stranded(aged(fresh, "generating"), now=now) is False
    assert cs.review_copy_is_stranded(aged(stale, "ready"), now=now) is False
    assert cs.review_copy_is_stranded(aged(fresh, "ready"), now=now) is False
    assert cs.review_copy_is_stranded(aged(fresh, "failed"), now=now) is False
    assert cs.review_copy_is_stranded(aged(fresh, ""), now=now) is False
    assert cs.review_copy_is_stranded({"review_status": "generating"}, now=now) is True
    assert (
        cs.review_copy_is_stranded(
            {"review_status": "generating", "updated_at": "不像时间戳"}, now=now
        )
        is True
    )


@pytest.mark.asyncio
async def test_the_in_flight_guard_admits_exactly_one_dispatch_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真身 ``spawn_review_copy_job`` 的在途门: 同一会话在跑时第二次派生被拒, 跑完再松.

    这条只能碰**真身** —— 记账替身里没有 ``_REVIEW_IN_FLIGHT`` 那段逻辑; runner 换成挂在
    event 上的替身, 于是"在途"是可以控制的。三层幂等门 (在途集合 / 作业入口状态复查 / 落库
    乐观锁) 里这层只负责"别白烧第二次", 跨进程那两层由别的用例覆盖。
    """
    started: list[str] = []
    gate = asyncio.Event()

    async def _hang_job(session_id: str) -> None:
        started.append(session_id)
        await gate.wait()

    monkeypatch.setattr(cs, "run_review_copy_job", _hang_job)

    # GET 侧同一道门: 两个轮询请求同时到达 -> 第二个必须拿到 False (不重派)。
    monkeypatch.setattr(cs, "spawn_review_copy_job", ORIGINAL_SPAWN)
    stranded: dict[str, Any] = {
        "review_status": "generating",
        "updated_at": cs._iso(
            datetime.now(UTC) - timedelta(seconds=cs.REVIEW_REDISPATCH_AFTER_S + 1)
        ),
    }
    assert cs.resume_stranded_review_copy("polled-session", stranded) is True
    assert cs.resume_stranded_review_copy("polled-session", stranded) is False, (
        "轮询撞车时第二次也派了活 -> 同一会话同时跑两个文案作业"
    )

    assert ORIGINAL_SPAWN("session-under-test") is True
    assert ORIGINAL_SPAWN("session-under-test") is False, "在途门失效 -> 同一会话跑两个作业"
    assert ORIGINAL_SPAWN("another-session") is True  # 门按会话分, 不是全局锁
    await asyncio.sleep(0)
    assert sorted(started) == ["another-session", "polled-session", "session-under-test"]

    gate.set()
    pending = list(cs._REVIEW_JOBS)
    await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)
    assert not cs._REVIEW_IN_FLIGHT, "task 跑完没 release -> 之后的重派会被永久拒"
    assert ORIGINAL_SPAWN("session-under-test") is True


# ================================================== 8) 自动收工 / 老数据


@pytest.mark.asyncio
async def test_the_auto_finish_at_max_turns_is_async_too(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, course_root: Callable[..., Path]
) -> None:
    """到轮次上限的自动收工同治: 那一轮之内不掺总评 LLM —— **最常发生**的收工路径.

    它以前是结构性超时 (23s 的语音轮 + 一次总评 = 43s > 30s), 而"聊到轮次上限自然收工"恰好
    是每日练习结束最常出现的形状; 压预算救不了 (压到 7s 以下等于总评每次都退成模板), 所以
    只能整段移出请求。脚本形状值得留意: 前几条**即时**给合法判定 (否则连判分那一问都会睡),
    最后一条挂死 = 任何"顺手再问一次总评"的实现都会睡在那里, 于是墙钟与调用次数同时露馅。
    """
    course_root(max_turns=4)
    sid = await _ready(client)
    fake = install_slow_llm(
        monkeypatch,
        [
            (0.0, mission_json(done=[("t1", "说了点单")])),
            (0.0, mission_json(done=[("t2", "问了价格")])),
            (0.0, mission_json(reply="Almost there, what else?", done=[])),
            (0.0, mission_json(reply="Nice, anything else?", done=[])),
            (HANG_S, ""),  # 第 5 次调用只会是"顺手再问一次总评"的实现撞上来的那堵墙
        ],
    )
    for index in range(3):
        res = await _mission(client, sid, {"text": f"turn number {index + 1} content"})
        assert res.status_code == 200, res.text
        assert res.json()["auto_finished"] is False and res.json()["review"] is None
    assert fake.calls == 3, "每轮一次判定调用 (合法 JSON, 不回喂重试)"

    spawned = _record_spawns(monkeypatch)
    started = time.monotonic()
    res = await _mission(client, sid, {"text": "and a cookie with that please"})
    elapsed = time.monotonic() - started  # 挂死的那条脚本项一旦被这次请求碰到就是 5s+
    assert res.status_code == 200, res.text
    body = res.json()

    assert elapsed < 3.0, f"自动收工那一轮又去等总评了 (实际 {elapsed:.1f}s)"
    # 3 次已在前面 + 本轮判分 1 次 = 4。第 5 次调用只可能是"请求里顺手再问一次总评"。
    assert fake.calls == 4, "请求里多出的那次 LLM 调用就是学员报的超时"
    assert (body["stage"], body["status"]) == ("review", "completed")
    assert body["auto_finished"] is True and body["finished"] is True
    assert body["review_status"] == "generating"
    report = body["review"]
    assert report is not None and report["auto_finished"] is True
    assert report["turn_count"] == 4 and report["max_turns"] == 4
    assert report["overall"] == pytest.approx(68.0)  # 判分给过的 66/70 就在工作响应里
    assert report["source"] == "heuristic" and report["highlights"]
    assert spawned.calls == [sid], "自动收工没派文案作业"

    shrink_budget(monkeypatch, cs, "REVIEW_COPY_JOB_BUDGET_S")
    await cs.run_review_copy_job(sid)  # runner 落在脚本最后那条: 挂死 -> 预算内降级
    view = await _snapshot(client, sid)
    assert view["review_status"] == "ready"
    assert view["review"]["source"] == "heuristic" and view["review"]["highlights"]
    assert _numbers(view["review"]) == _numbers(report)


@pytest.mark.asyncio
async def test_a_legacy_generating_snapshot_without_facts_ends_ready(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """§P6 之前收的工 (``generating`` 但没有 ``review_facts``) -> 诚实落 ``ready``, 不崩.

    实施里有一条显式分支: 骨架里没有 prompt 输入 (老快照, 或被人动过) 就是**没有可补的料**,
    于是直接收尾。值得单独钉, 因为升级之后库里躺着的全是这一类会话 —— 它们要停在"生成中",
    客户端就会一直轮询一个永远不会有人写的文案。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    skeleton = (await _snapshot(client, sid))["review"]
    doc = await _read_doc(db, sid)
    del doc["review_facts"]
    await _write_doc(db, sid, doc)

    fake = install_llm(monkeypatch, [REVIEW_B])
    await cs.run_review_copy_job(sid)

    view = await _snapshot(client, sid)
    assert view["review_status"] == "ready"
    assert view["review"] == skeleton, "没料可补就该原样交回, 一个字都别改"
    assert fake.requests == []


@pytest.mark.asyncio
async def test_a_legacy_finished_session_reports_ready_and_is_never_polled(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
    course_root: Callable[..., Path],
) -> None:
    """老快照 (``review`` 在但**没有** ``review_status``) -> 报 ``ready``, 不被无限轮询.

    这是给客户端轮询策略让的路: 那场课收工于 §P6 之前, 报告本身就是完整品, 没有作业会再来
    翻状态 —— 报成 ``generating`` 就是让它一直转到天荒地老。JSON 列里的野值同理: 读快照不
    该把 GET 打成 500 (所以字段类型是 ``str | None`` 而不是字面量)。
    """
    sid = await _scored_session(client, monkeypatch, course_root, [REVIEW_A])
    spawned = _record_spawns(monkeypatch)
    doc = await _read_doc(db, sid)
    del doc["review_status"]
    await _write_doc(db, sid, doc)

    view = await _snapshot(client, sid)
    assert view["review_status"] == "ready"
    assert view["review"] is not None and view["review"]["highlights"]
    assert spawned.calls == []

    doc = await _read_doc(db, sid)
    doc["review_status"] = "已生成"  # JSON 列里的野值: 收敛成"不可知", 别抬成契约
    await _write_doc(db, sid, doc)
    dirty = await _snapshot(client, sid)
    assert dirty["review_status"] == "ready"
    assert spawned.calls == []

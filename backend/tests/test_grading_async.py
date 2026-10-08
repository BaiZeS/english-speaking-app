"""实战轮判分的后台作业 (§A3) —— "判分移出请求" 的那一份契约.

生产实锤 (§0): 8 轮实战里 7 轮撞 15s 硬预算 —— 一次调用要塞台词 + 示范 + 润色 + 两个分 +
全量任务重判 (700 token), 实测 p50 22.5s, 而手机 OkHttp ``readTimeout`` 只有 30s。§A(D1) 的
修法是拆开: 请求内只出台词 (墙 14s), 判分 (p50 6.6s) 搬到请求之外。本文件钉这个新形状, 按
"客户端与运维会怎么踩"组织:

1. **作业必落终态** —— 成功 -> 该轮 ``grading.status="ready"``; LLM 不可用 -> ``failed``
   (没有润色也没有分数, 但**这一轮存在**); 崩了 -> ``_fail_grading`` 兜底成 ``failed``。
   **没有一条路径把轮次留在 ``pending``** (客户端拿它当轮询键, 留着就是无限轮询)。
2. **判分重放不幂等 = 硬门**: ``record_step_evidence`` 只 add、画像 EWMA 会被重复计入 ——
   同一轮只许落一次证据 (状态门 + 乐观锁)。
3. **重启兜底**: ``asyncio.create_task`` 不持久, 进程死在半路时轮次会停在 ``pending``;
   ``GET /sessions/{id}`` 过水位后**就地重派** (客户端不新增通道, ``grading_status`` 就是它
   的键)。
4. **失败必须静默**: 判分失败 = 没有润色, 不是"这一轮不存在" (D5 的 503 只属于台词拿不到)。
5. **作业只补判分列, 不动冻结的报告数值** (§P6 "数值一次写定" 仍在)。

手法沿用 ``test_review_async``: 作业一律由用例自己 ``await cs.run_mission_grading_job(sid)``
驱动 (conftest 的 autouse 已把 ``spawn_mission_grading_job`` 换成 no-op, 免得真任务活过内存
sqlite 的 dispose); 要断"派生了作业"就用 :func:`_record_grading_spawns` 记账。
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import course_sessions as cs
from app.core.errors import AppError
from app.models.db import AbilityEvent, PracticeSession
from app.services import llm_provider, scene_store
from tests.test_course_sessions import BRIEFING6, _open, _pass_briefing
from tests.test_drill_grader import install_llm
from tests.test_mission import _grade, _mission, _snapshot, generation_json, mission_json
from tests.test_scene_store import make_course_dict

FAKE_MODEL = "qwen3.8-max"

#: autouse 夹具会把模块属性换成 no-op; 导入期抓住原身, 供"在途幂等门"那条用例用。
ORIGINAL_GRADING_SPAWN = cs.spawn_mission_grading_job
#: 一轮判分 (``MissionTurnJudgement`` 形状): 语法 66 / 词汇 70 + 润色 + 任务判定。
_GRADE_T1 = mission_json(
    done=[("t1", "说了点单内容")],
    polish={
        "original": "How much money?",
        "polished": "How much is that in total?",
        "explanation_cn": "问价格说 how much is that。",
        "polished_cn": "一共多少钱",
    },
)


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_grading_state() -> AsyncIterator[None]:
    """模块级派生门 (``_GRADING_IN_FLIGHT`` / ``_GRADING_JOBS``) 是用例之间的共享状态."""
    cs._GRADING_IN_FLIGHT.clear()
    cs._GRADING_JOBS.clear()
    yield
    pending = [task for task in cs._GRADING_JOBS if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    cs._GRADING_IN_FLIGHT.clear()
    cs._GRADING_JOBS.clear()


@pytest.fixture(autouse=True)
def course_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    """假课 ``scene_alpha`` (``BRIEFING6``); 需要别的形状 (如 ``max_turns=1``) 的用例再覆写一次."""
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

    _make()
    yield _make
    scene_store.invalidate_cache()


class _GradingSpawnRecorder:
    """把 ``spawn_mission_grading_job`` 换成**只记账不真开任务**的替身."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, session_id: str) -> bool:
        self.calls.append(session_id)
        return True


def _record_grading_spawns(monkeypatch: pytest.MonkeyPatch) -> _GradingSpawnRecorder:
    recorder = _GradingSpawnRecorder()
    monkeypatch.setattr(cs, "spawn_mission_grading_job", recorder)
    return recorder


async def _read_doc(db: AsyncSession, sid: str) -> dict[str, Any]:
    row = (
        (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalars().one()
    )
    return copy.deepcopy(dict(row.doc))


async def _write_doc(db: AsyncSession, sid: str, doc: dict[str, Any]) -> None:
    """整体换新写回 (JSON 列原地改不会脏 —— ``_save_doc`` 的同一条坑, 测试也得守)."""
    row = (
        (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalars().one()
    )
    row.doc = copy.deepcopy(doc)
    await db.commit()


async def _age_snapshot(db: AsyncSession, sid: str, *, seconds: float) -> dict[str, Any]:
    """把快照的 ``updated_at`` 往回拨 —— 重派水位读的就是它."""
    doc = await _read_doc(db, sid)
    doc["updated_at"] = cs._iso(datetime.now(UTC) - timedelta(seconds=seconds))
    await _write_doc(db, sid, doc)
    return doc


async def _ready_sid(client: AsyncClient) -> str:
    sid = await _open(client)
    await _pass_briefing(client, sid)
    return sid


async def _events_of(db: AsyncSession, sid: str, step_id: str) -> list[AbilityEvent]:
    return list(
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id == step_id
                )
            )
        )
        .scalars()
        .all()
    )


# ==================================================== 1) 正常路: 判分回填 + 只落一次证据


@pytest.mark.asyncio
async def test_a_pending_turn_is_graded_and_backfilled_into_the_snapshot(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """请求只出台词 (``grading=pending``), 作业跑完把它补成 ``ready`` + 润色/分数/清单."""
    sid = await _ready_sid(client)
    install_llm(
        monkeypatch,
        generation=[generation_json(reply="Small or medium?")],
        grading=[_GRADE_T1],
    )
    body = (await _mission(client, sid, {"text": "How much money?"})).json()
    assert body["grading_status"] == "pending" and body["polish"] is None

    snapshot = await _grade(client, sid)
    entry = snapshot["mission"]["turns"][0]
    assert snapshot["grading_status"] == "ready"
    assert entry["grading"]["status"] == "ready"
    assert entry["polish"]["polished"] == "How much is that in total?"
    assert entry["sub_scores"]["grammar"] == pytest.approx(66.0)
    assert entry["source"] == "llm" and entry["llm_source"] == FAKE_MODEL
    # 画像证据: 语法/词汇各一条 (发音那两条要真音频, 本机没有)
    dims = {event.dimension for event in await _events_of(db, sid, "m1")}
    assert dims == {"grammar", "vocabulary"}
    # step 行也回填了 (复盘报告按行聚合, 而报告是收工那一刻的快照)
    step = (
        await db.execute(
            select(cs.PracticeStep).where(
                cs.PracticeStep.session_id == sid, cs.PracticeStep.step_id == "m1"
            )
        )
    ).scalar_one()
    assert step.score_grammar == pytest.approx(66.0)
    assert step.annotated_json["polish"]["polished_cn"] == "一共多少钱"
    assert step.annotated_json["grading"]["status"] == "ready"


@pytest.mark.asyncio
async def test_rerunning_the_job_never_double_counts_the_evidence(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**重放不幂等 = 硬门**: 判分已落 (``ready``) 的轮次再跑一次, 证据不许翻倍.

    ``record_step_evidence`` 只 add、画像 EWMA 会被重复计入, 所以终态门的谓词检查
    ("这一轮还是 pending/failed 吗") 是唯一的防线。变异实测: 把谓词去掉, 这条用例立刻红
    (事件从 2 条变 4 条, 画像也被再拉一次)。
    """
    sid = await _ready_sid(client)
    install_llm(
        monkeypatch,
        generation=[generation_json()],
        grading=[_GRADE_T1],
    )
    await _mission(client, sid, {"text": "How much money?"})
    await _grade(client, sid)
    before = await _events_of(db, sid, "m1")
    assert len(before) == 2

    # 再跑两次 (模拟重派/跨进程重复): 谓词不成立 -> 直接跳过, 一个字都不写
    await cs.run_mission_grading_job(sid)
    await cs.run_mission_grading_job(sid)
    after = await _events_of(db, sid, "m1")
    assert len(after) == len(before), "判分重放把同一轮的证据又落了一遍 (画像会双计)"
    assert {event.id for event in after} == {event.id for event in before}


@pytest.mark.asyncio
async def test_the_job_that_loses_the_optimistic_race_leaves_no_evidence(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """落库输给乐观锁 -> 那一刀 (含刚 ``add`` 的画像证据) **随事务一起回滚**.

    这是"判分重放不幂等"的另一半: 谓词门挡的是"已经 ready 的轮次", 而这道门挡的是
    "两个作业同时进来"—— 输家必须一个字都不留 (事件流水 + 画像 EWMA 都不能双计), 状态停在
    ``pending`` 好让下一次过水位的 GET 重派它。测试跑在 sqlite 的 StaticPool 上, 制造不了真
    并发, 所以这里钉的是**输家的行为**(与 ``test_review_async`` 那条同一手法)。
    """
    sid = await _ready_sid(client)
    install_llm(monkeypatch, generation=[generation_json()], grading=[_GRADE_T1])
    await _mission(client, sid, {"text": "How much money?"})

    async def _lose(*args: Any, **kwargs: Any) -> int:
        raise AppError(
            409, "this session was updated by another request", "SESSION_CONCURRENT_UPDATE"
        )

    monkeypatch.setattr(cs, "_save_doc", _lose)
    await cs.run_mission_grading_job(sid)  # 不抛 = 作业不会把 traceback 甩进无人接的 task

    doc = await _read_doc(db, sid)
    assert doc["mission"]["turns"][0]["grading"]["status"] == "pending", (
        "输家改了状态 -> 快照会停在 ready, 而那一轮的分数/证据其实一条都没落"
    )
    assert await _events_of(db, sid, "m1") == []  # 证据行随事务回滚 (画像不双计)
    step = (
        await db.execute(
            select(cs.PracticeStep)
            .where(cs.PracticeStep.session_id == sid, cs.PracticeStep.step_id == "m1")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert step.score_grammar is None  # step 行的回填也没落
    assert step.annotated_json["grading"]["status"] == "pending"


# ==================================================== 2) 三条出口: 静默 + 必落终态


@pytest.mark.asyncio
async def test_a_hung_llm_marks_the_turn_failed_not_the_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判分拿不到 -> 该轮 ``failed`` (没有润色/分数), 但**这一轮仍然存在** (§A3 的静默).

    ``judge_turn`` 自己降级成词面快判, 所以作业不抛、请求早已 200 —— 学员看到的是"这一轮
    没有润色", 绝不是"这一轮不存在"。
    """
    sid = await _ready_sid(client)
    install_llm(
        monkeypatch,
        generation=[generation_json()],
        # 判分兜里只有**坏输出**: 两次都不合规 -> ``_judge`` 抛 -> judge_turn 降级成词面快判。
        grading=["这不是 JSON", "这也不是 JSON"],
    )
    res = await _mission(client, sid, {"text": "How much money?"})
    assert res.status_code == 200, res.text  # 请求不受判分影响
    snapshot = await _grade(client, sid)
    entry = snapshot["mission"]["turns"][0]
    assert entry["grading"]["status"] == "failed"
    assert entry["polish"] is None and entry["sub_scores"]["grammar"] is None
    assert entry["source"] == "heuristic"
    # 台词与任务勾都还在 —— 判分失败没吞掉这一轮
    assert entry["reply"] and snapshot["mission"]["turn_count"] == 1
    assert snapshot["grading_status"] == "failed"  # 终态: 客户端不必再轮询


@pytest.mark.asyncio
async def test_an_unexpected_crash_still_lands_the_turn_terminal(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """作业里抛预期外异常 -> 收敛成 ``failed`` 终态 (绝不留在 ``pending``)."""
    sid = await _ready_sid(client)
    install_llm(monkeypatch, generation=[generation_json()], grading=[_GRADE_T1])
    await _mission(client, sid, {"text": "How much money?"})

    async def _boom(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("数据库抖了一下")

    monkeypatch.setattr(cs, "_publish_grading", _boom)
    await cs.run_mission_grading_job(sid)  # 不抛: 兜底把状态收敛掉

    doc = await _read_doc(db, sid)
    assert doc["mission"]["turns"][0]["grading"]["status"] == "failed"
    assert doc["mission"]["grading"]["status"] == "failed"
    # 台词那一半仍在 (作业崩了不该把学员已经看到的那一轮抹掉)
    assert doc["mission"]["turns"][0]["reply"]
    assert await _events_of(db, sid, "m1") == []  # 影像证据一条都没落 (作业根本没写到判分那一步)


@pytest.mark.asyncio
async def test_the_job_skips_quietly_when_the_session_row_is_gone(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """会话没了 (被删/测试收尾) -> 静默返回, 不抛 (后台任务不能无声死去)."""
    install_llm(monkeypatch, grading=[_GRADE_T1])
    started = time.monotonic()
    await cs.run_mission_grading_job("no-such-session")
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_a_legacy_turn_without_grading_key_is_never_regraded(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§A3 之前收的老会话 (turn_entry 里没有 ``grading`` 键) **不许**被重评.

    它的判分早在请求里同步做完了 —— 把 ``""`` 当成 ``pending`` 会重烧一次 LLM, 还会把
    画像证据再落一遍 (双计)。这条用例是老数据的门。
    """
    sid = await _ready_sid(client)
    install_llm(monkeypatch, generation=[generation_json()], grading=[_GRADE_T1])
    await _mission(client, sid, {"text": "How much money?"})
    doc = await _read_doc(db, sid)
    legacy = doc["mission"]["turns"][0]
    legacy.pop("grading")
    legacy["source"] = "llm"  # 老会话的判分结果本来就在 turn_entry 里
    legacy["grammar_score"] = 80.0
    doc["mission"].pop("grading", None)
    await _write_doc(db, sid, doc)

    spawned: list[str] = []
    monkeypatch.setattr(cs, "spawn_mission_grading_job", lambda sid_: spawned.append(sid_) or True)
    snapshot = await _snapshot(client, sid)
    assert snapshot["grading_status"] == "ready"  # 老会话报 ready, 不让客户端无限轮询
    assert spawned == []  # GET 也不重派
    await cs.run_mission_grading_job(sid)  # 即使被派了也什么都不做
    assert await _events_of(db, sid, "m1") == []


# ==================================================== 3) 重启兜底: GET 就地重派


def test_redispatch_thresholds_are_per_status() -> None:
    """水位是**纯函数**的读数 (便于单测): ``pending`` 2 倍预算, ``failed`` 1 倍."""
    assert cs.GRADING_REDISPATCH_AFTER_S == cs.GRADING_JOB_BUDGET_S * 2
    base = {
        "mission": {"turns": [{"index": 1, "grading": {"status": "pending", "at": "x"}}]},
        "updated_at": cs._iso(datetime.now(UTC)),
    }
    assert cs.mission_grading_is_stranded(base) is False  # 刚落的 pending: 作业还在跑
    fresh = copy.deepcopy(base)
    fresh["updated_at"] = cs._iso(datetime.now(UTC) - timedelta(seconds=cs.GRADING_JOB_BUDGET_S))
    assert cs.mission_grading_is_stranded(fresh) is False  # 一个周期还不够 (活着的作业)
    stale = copy.deepcopy(base)
    stale["updated_at"] = cs._iso(
        datetime.now(UTC) - timedelta(seconds=cs.GRADING_REDISPATCH_AFTER_S + 1)
    )
    assert cs.mission_grading_is_stranded(stale) is True

    failed = copy.deepcopy(stale)
    failed["mission"]["turns"][0]["grading"]["status"] = "failed"
    assert cs.mission_grading_is_stranded(failed) is True  # 作业已停, 一个周期后就该重试
    early = copy.deepcopy(failed)
    early["updated_at"] = cs._iso(datetime.now(UTC) - timedelta(seconds=1))
    assert cs.mission_grading_is_stranded(early) is False  # 刚失败: 别立刻重烧
    # 老会话 (没有 grading 键) 永远不是"停摆" -> 不会被重判
    assert (
        cs.mission_grading_is_stranded({"mission": {"turns": [{"index": 1}]}, "updated_at": "x"})
        is False
    )
    # 没有 mission 分区 / 没有快照时刻 -> 不算停摆 / 算已过水位
    assert cs.mission_grading_is_stranded({}) is False


@pytest.mark.asyncio
async def test_grading_job_never_loses_a_line(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**重启兜底** (§A3): 崩在"快照已落"与"作业派生"之间的那一轮, 由 GET 过水位后救回来.

    这一条是本次改造里最容易漏的活: ``asyncio.create_task`` 不持久, 进程死在半路时
    ``turn_entry["grading"]`` 会永远停在 ``pending`` —— 学员看到的润色/分数就永远不来, 而
    没有任何东西会再推它。GET 是客户端唯一的轮询通道 (它每一跳都回 ``grading_status``),
    所以兜底必须长在那儿 (与 §P6 的总评文案同一先例)。

    三段断言分别对应三件事: ① 刚落下时**不**重派 (作业还在跑); ② 过水位后重派;
    ③ 重派出来的作业把那轮补完 (只补一次, 证据不翻倍)。
    """
    sid = await _ready_sid(client)
    install_llm(monkeypatch, generation=[generation_json()], grading=[_GRADE_T1])
    spawned = _record_grading_spawns(monkeypatch)
    await _mission(client, sid, {"text": "How much money?"})
    assert spawned.calls == [sid]  # 请求自己派过一次 (记账替身)

    # ① 作业从没跑起来 (等价于进程死在半路): 快照里那一轮还是 pending
    doc = await _read_doc(db, sid)
    assert doc["mission"]["turns"][0]["grading"]["status"] == "pending"
    await _snapshot(client, sid)
    assert spawned.calls == [sid], "刚落的 pending 就被重派 -> 同一会话会跑两个作业"

    # ② 把快照时刻往回拨过水位 -> 同一个 GET 就地重派
    doc = await _age_snapshot(db, sid, seconds=cs.GRADING_REDISPATCH_AFTER_S + 1)
    view = await _snapshot(client, sid)
    assert view["grading_status"] == "pending"
    assert spawned.calls == [sid, sid], "停摆的判分作业没有被重派 -> 那一轮永远等不到润色"

    # ③ 重派出来的作业真的把它补完 (证据只有一份)
    snapshot = await _grade(client, sid)
    assert snapshot["grading_status"] == "ready"
    assert snapshot["mission"]["turns"][0]["grading"]["status"] == "ready"
    assert len(await _events_of(db, sid, "m1")) == 2
    # 补完之后 GET 不再重派 (终态没有水位)
    await _snapshot(client, sid)
    assert spawned.calls == [sid, sid]


@pytest.mark.asyncio
async def test_a_failed_turn_is_retried_at_the_shorter_threshold(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``failed`` 轮次一个预算周期后就能重试 (不必等下一次重启), 且能真的翻身成 ready."""
    sid = await _ready_sid(client)
    install_llm(monkeypatch, generation=[generation_json()], grading=["坏", "也坏"])
    spawned = _record_grading_spawns(monkeypatch)
    await _mission(client, sid, {"text": "How much money?"})
    snapshot = await _grade(client, sid)
    assert snapshot["mission"]["turns"][0]["grading"]["status"] == "failed"
    events_before = await _events_of(db, sid, "m1")

    # 还没过水位: GET 不重派
    await _snapshot(client, sid)
    assert spawned.calls == [sid]

    # 过了一个预算周期: GET 重派一次; 这次判分好了 -> ready
    await _age_snapshot(db, sid, seconds=cs.GRADING_JOB_BUDGET_S + 1)
    await _snapshot(client, sid)
    assert spawned.calls == [sid, sid]
    install_llm(monkeypatch, grading=[_GRADE_T1])
    healed = await _grade(client, sid)
    assert healed["mission"]["turns"][0]["grading"]["status"] == "ready"
    assert healed["mission"]["turns"][0]["polish"]["polished"] == "How much is that in total?"
    events_after = await _events_of(db, sid, "m1")
    assert len(events_after) == len(events_before) + 2  # 只多了这一次判分的那两条


@pytest.mark.asyncio
async def test_the_in_flight_guard_admits_exactly_one_dispatch_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """在途幂等门: 同一会话同时只许一个判分作业 (跨进程由作业里的谓词 + 乐观锁兜)."""
    original = ORIGINAL_GRADING_SPAWN
    started: list[str] = []
    gate = asyncio.Event()

    async def _slow(session_id: str) -> None:
        started.append(session_id)
        await gate.wait()

    monkeypatch.setattr(cs, "run_mission_grading_job", _slow)
    assert original("s1") is True
    assert original("s1") is False, "在途门失效 -> 同一会话会跑两个判分作业"
    assert original("s2") is True
    await asyncio.sleep(0)
    assert sorted(started) == ["s1", "s2"]
    gate.set()
    pending = list(cs._GRADING_JOBS)
    await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)
    assert not cs._GRADING_IN_FLIGHT, "task 跑完没 release -> 之后的重派会被永久拒"
    assert original("s1") is True


# ==================================================== 4) 收工路上也派判分作业


@pytest.mark.asyncio
async def test_the_auto_finish_spawns_both_jobs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, course_root: Callable[..., Path]
) -> None:
    """到轮次上限自动收工: **判分作业与总评文案作业都要派** (§A3 的显式要求).

    只有总评作业时, 最后一轮的润色/分数没人补, 而"聊到轮次上限自然收工"恰是每日练习结束
    最常发生的形状 —— 学员在复盘页会一直看不到那一轮。
    """
    course_root(max_turns=4)  # 课表下限就是 4 (SceneCourse 校验)
    sid = await _ready_sid(client)
    grading_spawns = _record_grading_spawns(monkeypatch)
    copy_spawns: list[str] = []
    monkeypatch.setattr(cs, "spawn_review_copy_job", lambda sid_: copy_spawns.append(sid_) or True)
    install_llm(
        monkeypatch,
        generation=[generation_json()],
        grading=[_GRADE_T1],
        review=[json.dumps({"highlights": [], "improvements": []})],
    )
    for _ in range(3):
        res = await _mission(client, sid, {"text": "How much money?"})
        assert res.json()["auto_finished"] is False
    body = (await _mission(client, sid, {"text": "How much money?"})).json()
    assert body["auto_finished"] is True and body["review"] is not None
    # 判分作业: 每一轮都派 (4 次) —— 最后一轮也不例外 (否则它的润色永远没人补)
    assert grading_spawns.calls == [sid] * 4
    # 总评文案作业: 只有收工那一轮派
    assert copy_spawns == [sid]

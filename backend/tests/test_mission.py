"""实战对话 (mission) + 复盘报告 端点测试 (§5.3/§5.5-2/§5.6, 阶段 P3).

§A(D1) 拆调用之后一轮实战是**两段**: 请求内的台词生成 (:func:`mission_engine.generate_turn`)
与后台作业里的判分 (:func:`course_sessions.run_mission_grading_job`)。所以本文件的假 LLM
按 prompt 形状给两份料 (``install_llm(..., generation=[...], grading=[...])``), 而"判分那半边"
由用例自己 ``await run_mission_grading_job(sid)`` 驱动 (conftest 已把派生换成 no-op)。

按"客户端会怎么踩"组织:

* 打完基础 -> ``/mission`` 逐轮 -> 任务累积打勾 -> cleared -> ``/finish-mission`` 出
  ReviewReport -> 报告持久化 + history 落行 (老历史页形状);
* 门禁可区分: 阶段未解锁 / 归属 / 收工后的 409 各不相同, 越权 403;
* 任务状态**累积合并** + 幂等 (同一段话连说两轮不重复打勾; LLM 翻供不回退);
* **D5**: 台词拿不到 -> 503 ``TURN_GENERATION_UNAVAILABLE``, 这一轮**不落库不前进** ——
  旧版"坏 JSON 回放到剧本"那条降级路已删 (它是"每轮同一句"的根因), 用例改为断 503 +
  无副作用 + 重发不重计;
* ``max_turns`` 到顶自动收工 (响应带数值骨架 + 两个作业都派出);
* 讯飞路径: 音频缺 IAT -> 400 TRANSCRIPT_UNAVAILABLE; ISE 配了才产
  ``transcript_anchored`` 发音证据 (请求内就落, 逐词分进 step 行); ISE 失败回退 stub 时
  证据**整体丢弃**;
* ``/hint`` 不调 LLM、不改判定, 只把下一个判定回合标 ``costs_score``.

Mock 手法沿用 T3 (``tests.test_drill_grader``): ``install_llm`` 换掉 ``AsyncOpenAI`` 并按
prompt 形状路由; 本文件自带 **autouse** provider 复位 —— 漏了会把"LLM 已配置"
泄漏给后面的模块 (``test_dialogue_stub`` 那批断言会莫名变红, T3 踩过)。
"""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import course_sessions
from app.config import settings
from app.main import app
from app.models.db import AbilityEvent, AbilityProfile, AnnotatedDiff, History, PracticeStep
from app.services import drill_grader as dg
from app.services import llm_provider, scene_store
from app.services import mission_engine as me
from tests.test_course_sessions import BRIEFING6, _pass_briefing
from tests.test_drill_grader import FakeASR, FakeIAT, install_llm
from tests.test_scene_store import make_course_dict, write_course

DEV = "dev-session"  # 与 test_course_sessions 的 helper 共用身份 (_pass_briefing 写死了它)
PCM_B64 = base64.b64encode(b"\x00\x01" * 3200).decode()  # 200ms 假 PCM


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.fixture
def scene_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_course(tmp_path, "scene_alpha", "daily", briefing=BRIEFING6)
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path  # type: ignore[misc]
    scene_store.invalidate_cache()


def generation_json(
    *,
    reply: str = "How about a size? We have small and large.",
    reply_cn: str = "要哪种杯型, 我们有小杯和大杯",
    suggestion: str = "Can I change that to a large?",
    suggestion_cn: str = "可以改成大杯吗",
    learner_cn: str = "我想要一杯中杯咖啡。",
) -> str:
    """台词生成的 JSON (§A1 的 ``TurnGeneration`` 五字段形状)."""
    return json.dumps(
        {
            "reply": reply,
            "reply_cn": reply_cn,
            "suggestion": suggestion,
            "suggestion_cn": suggestion_cn,
            "learner_cn": learner_cn,
        },
        ensure_ascii=False,
    )


def mission_json(
    *,
    polish: dict[str, Any] | None = None,
    grammar: float | None = 66.0,
    vocabulary: float | None = 70.0,
    done: list[tuple[str, str]] | None = None,
) -> str:
    """判分作业的 JSON (§A1 收缩后的 ``MissionTurnJudgement``: 只判分, 不产台词)."""
    return json.dumps(
        {
            "polish": polish,
            "grammar_score": grammar,
            "vocabulary_score": vocabulary,
            "task_progress": [
                {"id": task_id, "done": True, "evidence": evidence}
                for task_id, evidence in (done or [])
            ],
        },
        ensure_ascii=False,
    )


async def _snapshot(client: AsyncClient, sid: str, device: str = DEV) -> dict[str, Any]:
    """客户端唯一的轮询通道 (``grading_status`` / 回填后的 turn 都在这里)."""
    res = await client.get(f"/api/v1/sessions/{sid}", params={"device_id": device})
    assert res.status_code == 200, res.text
    return dict(res.json())


def _graded_entry(snapshot: dict[str, Any], turn_index: int = -1) -> dict[str, Any]:
    """快照里某一轮的 turn_entry (默认最后一轮) —— 判分回填后的样子."""
    turns = list(snapshot["mission"]["turns"])
    if turn_index < 0:
        return dict(turns[-1])
    return dict(next(turn for turn in turns if turn["index"] == turn_index))


async def _grade(client: AsyncClient, sid: str) -> dict[str, Any]:
    """驱动一次判分作业 (§A3) 并取回快照.

    测试直接 ``await run_mission_grading_job`` 而不是让它真 ``create_task`` —— conftest 的
    ``_no_detached_grading_jobs`` 已把 spawn 换成 no-op (同 ``run_review_copy_job`` 的口径)。
    """
    await course_sessions.run_mission_grading_job(sid)
    return await _snapshot(client, sid)


async def _open(client: AsyncClient, scene_id: str = "scene_alpha") -> str:
    res = await client.post(
        "/api/v1/sessions",
        json={"device_id": DEV, "kind": "scene_course", "scene_id": scene_id},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["session_id"])


async def _ready(client: AsyncClient) -> str:
    """开好局并把打基础全做完 (无凭据 -> 启发式/stub, 画像不动, 与 mission 解耦)."""
    sid = await _open(client)
    await _pass_briefing(client, sid)
    return sid


async def _mission(client: AsyncClient, sid: str, payload: dict[str, Any]) -> Any:
    body = {"device_id": DEV, **payload}
    return await client.post(f"/api/v1/sessions/{sid}/mission", json=body)


async def _finish(client: AsyncClient, sid: str) -> dict[str, Any]:
    """主动收工 —— §P6 之后是 **202** + 确定性数值骨架, AI 文案改由后台作业补。

    这里的断言就是新契约本身: 请求**不再**同步等 LLM (那正是学员看到 "timeout"
    的原因), 所以响应里没有 ``report``, 只有一盏 ``review_status="generating"`` 的灯。
    """
    res = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["stage"] == "review" and body["status"] == "completed"
    assert body["review_status"] == "generating"
    assert "report" not in body
    return body


async def _report(client: AsyncClient, sid: str, *, run_copy_job: bool = True) -> dict[str, Any]:
    """取复盘报告: 先驱动后台文案作业, 再走客户端真正会走的 ``GET /sessions/{id}``。

    测试直接 ``await run_review_copy_job`` 而不是让它真 ``create_task`` —— conftest 的
    ``_no_detached_review_jobs`` 已把 spawn 换成 no-op (与 ``test_course_generator``
    驱动 ``run_generation_job`` 同一手法)。``run_copy_job=False`` 用来看**骨架态**:
    数值齐全、文案是确定性模板, 这正是 202 返回后学员立刻能读到的那份。
    """
    if run_copy_job:
        await course_sessions.run_review_copy_job(sid)
    snap = await client.get(f"/api/v1/sessions/{sid}", params={"device_id": DEV})
    assert snap.status_code == 200, snap.text
    view = snap.json()
    if run_copy_job:
        assert view["review_status"] == "ready", view["review_status"]
    report = view["review"]
    assert isinstance(report, dict), report
    return report


# ============================================================ 阶段门禁


@pytest.mark.asyncio
async def test_mission_before_briefing_is_wrong_stage(
    client: AsyncClient, scene_root: Path
) -> None:
    sid = await _open(client)
    res = await _mission(client, sid, {"text": "A medium coffee please."})
    assert res.status_code == 409 and res.json()["error"]["code"] == "WRONG_STAGE"


# ============================================================ happy path (mock LLM)


@pytest.mark.asyncio
async def test_mission_loop_clears_tasks_and_finishes_with_report(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    sid = await _ready(client)  # 先打完基础 (启发式), 再装假 LLM, 免得判分吃掉剧本回复
    fake = install_llm(
        monkeypatch,
        generation=[
            generation_json(
                reply="How about a size? We have small and large.",
                suggestion="Can I change that to a large?",
                learner_cn="我能不能来一杯中杯咖啡",
            ),
            generation_json(
                reply="Sure — that comes to three dollars. Anything else?",
                suggestion="No, that's all. Thanks!",
            ),
        ],
        grading=[
            mission_json(done=[("t1", "说了点单内容")]),
            mission_json(
                done=[("t1", "说了点单内容"), ("t2", "问了价格")],
                polish={
                    "original": "How much money?",
                    "polished": "How much is that in total?",
                    "explanation_cn": "问价格说 how much is that。",
                    "polished_cn": "一共多少钱",
                },
            ),
        ],
        review=[
            json.dumps(
                {
                    "highlights": ["点单和问价都当面说出口了, 沟通目的达成。"],
                    "improvements": ["语法: 特殊疑问句的语序再练一轮。"],
                },
                ensure_ascii=False,
            )
        ],
    )

    first = await _mission(client, sid, {"text": "Can I get a medium coffee?"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["turn_index"] == 1 and body["transcript"] == "Can I get a medium coffee?"
    assert body["reply"].startswith("How about") and body["suggestion"]
    # §A(D1): 请求里只有台词那一半 —— 润色/语法/词汇**本轮恒为空**, 判分在后台。
    assert body["polish"] is None and body["sub_scores"]["grammar"] is None
    assert body["source"] == "pending" and body["grading_status"] == "pending"
    # D4 双语: 台词/示范/学员句三处的中文都在 (客户端渲染; 缺省是 "")
    assert body["reply_cn"] and body["suggestion_cn"] and body["learner_cn"]
    assert body["llm_source"] == "qwen3.8-max" and body["costs_score"] is False
    # 词面快判先顶 (§A3): t1 的 hint_en 就在这句话里, 不必等判分作业。
    assert body["newly_done"] == [
        {"id": "t1", "evidence": "词面覆盖了任务示范用语 (启发式快判, 未经语义核对)"}
    ]
    assert [view["done"] for view in body["checklist"]] == [True, False, False]
    assert body["cleared"] is False and body["max_turns"] == 8
    assert body["ability_events"] == []  # 没配讯飞 + 判分还没跑 -> 本轮没有证据

    # 判分作业跑完: 润色/语法/词汇回填进快照 (客户端拿 GET 回填, §A3 不新增端点)。
    graded = await _grade(client, sid)
    assert graded["grading_status"] == "ready"
    entry = _graded_entry(graded, 1)
    assert entry["grading"]["status"] == "ready"
    assert entry["source"] == "llm" and entry["llm_source"] == "qwen3.8-max"
    assert entry["sub_scores"]["grammar"] == pytest.approx(66.0)
    assert entry["sub_scores"]["vocabulary"] == pytest.approx(70.0)
    assert entry["newly_done"][0]["id"] == "t1"  # 快判那条保留 (去重后追加)
    grammar_event = next(
        event
        for event in (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id == "m1"
                )
            )
        )
        .scalars()
        .all()
        if event.dimension == "grammar"
    )
    assert grammar_event.weight == 1.0 and grammar_event.source_kind == "llm"

    second = (await _mission(client, sid, {"text": "How much money?"})).json()
    assert second["turn_index"] == 2
    # 快判先顶: 这句就是 t2 的 hint_en, 所以 cleared 当场就翻了 (不必等判分)。
    assert second["cleared"] is True
    assert second["newly_done"] == [
        {"id": "t2", "evidence": "词面覆盖了任务示范用语 (启发式快判, 未经语义核对)"}
    ]
    assert second["polish"] is None  # 判分还在后台
    optional_task = next(view for view in second["checklist"] if view["id"] == "t3")
    assert optional_task["required"] is False and optional_task["done"] is False

    graded2 = await _grade(client, sid)
    entry2 = _graded_entry(graded2, 2)
    assert entry2["polish"]["polished"] == "How much is that in total?"
    assert entry2["polish"]["polished_cn"] == "一共多少钱"  # D4 双语润色也带中文

    await _finish(client, sid)
    report = await _report(client, sid)

    assert report["cleared"] is True and report["auto_finished"] is False
    assert report["turn_count"] == 2 and report["max_turns"] == 8
    assert report["dims"]["grammar"] == pytest.approx(66.0)  # 只聚合可信来源 (启发式 100 不掺)
    assert report["dims"]["vocabulary"] == pytest.approx(70.0)
    assert report["dims"]["pronunciation"] is None  # 全程没有真 ISE 证据 != stub 的假 95
    assert report["overall"] == pytest.approx(68.0)
    assert report["pronunciation_subs"]["pronunciation"] is None  # 连读行是 stub -> 不计
    assert report["highlights"] == ["点单和问价都当面说出口了, 沟通目的达成。"]
    assert report["improvements"] == ["语法: 特殊疑问句的语序再练一轮。"]
    assert [view["done"] for view in report["checklist"]] == [True, True, False]
    assert report["transcript_pairs"] and report["transcript_pairs"][0]["polished"] == (
        "How much is that in total?"
    )
    assert report["transcript_pairs"][0]["source"] == "mission"
    assert set(report["new_tokens"]) >= {"order", "sugar"}  # 转写里真说过的核心词
    # 开局基线全 None (本机 brief 轮全被门控) -> 拉动不可知 -> None, 别拿 0 冒充
    assert report["ability_delta"] == {
        "pronunciation": None,
        "grammar": None,
        "vocabulary": None,
        "fluency": None,
    }
    assert report["source"] == "llm" and report["llm_source"] == "qwen3.8-max"
    assert fake.requests[-1]["model"] == "qwen3.8-max"  # 复盘文案也是服务端默认模型

    steps = (
        (await db.execute(select(PracticeStep).where(PracticeStep.session_id == sid)))
        .scalars()
        .all()
    )
    mission_rows = sorted(
        (s for s in steps if s.step_type == "mission_turn"), key=lambda s: s.step_id
    )
    assert [s.step_id for s in mission_rows] == ["m1", "m2"]
    assert mission_rows[0].ok is True and mission_rows[0].transcript  # ok = 本轮推进了任务
    assert mission_rows[0].score_grammar == 66.0 and mission_rows[0].score_pronunciation is None
    assert mission_rows[1].annotated_json["polish"]["original"] == "How much money?"
    events = (
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id.in_(["m1", "m2"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {(e.dimension, e.weight, e.source_kind) for e in events} == {
        ("grammar", 1.0, "llm"),
        ("vocabulary", 1.0, "llm"),
    }
    gated = (
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id.in_(["f1", "f4"])
                )
            )
        )
        .scalars()
        .all()
    )  # 打基础的 stub/heuristic 证据也进了流水 (w=0, 审计用)
    assert gated and all(e.weight == 0.0 for e in gated)
    profiles = (await db.execute(select(AbilityProfile))).scalars().all()
    assert len(profiles) == 1 and profiles[0].grammar == pytest.approx(66.0)  # 种子化首样本
    assert profiles[0].cefr_level is None  # 测评 (P4) 之前权威 CEFR 恒 null
    diffs = (await db.execute(select(AnnotatedDiff))).scalars().all()
    assert [(d.origin, d.polished) for d in diffs] == [("mission", "How much is that in total?")]
    history_rows = (await db.execute(select(History))).scalars().all()
    assert len(history_rows) == 1
    row = history_rows[0]
    assert row.book == "scenes" and row.line_id == sid and row.audio_path == "scene_alpha"
    assert 0 < row.lesson_id < 100_000_000  # script_lesson_no 稳定散列, (book, lesson) 聚合可玩
    assert row.score_total == pytest.approx(report["overall"])

    # 收工后一切可变端点被挡; 崩溃恢复快照带 review
    late = await _mission(client, sid, {"text": "one more"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "SESSION_NOT_ACTIVE"
    finish_again = await client.post(
        f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV}
    )
    assert finish_again.status_code == 409
    snapshot = (await client.get(f"/api/v1/sessions/{sid}", params={"device_id": DEV})).json()
    assert snapshot["stage"] == "review" and snapshot["review"]["session_id"] == sid
    assert snapshot["mission"]["finished"] is True and snapshot["mission"]["turn_count"] == 2
    assert snapshot["mission"]["opening"]["a"] == "Hi, what can I get you?"


@pytest.mark.asyncio
async def test_cleared_mission_keeps_talking_until_finish(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """通关后不封麦: 学员可以继续聊, 直到 finish-mission 才收工 (P6 的聊天体验)."""
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        generation=[
            generation_json(reply="Coffee it is. Small or medium?"),
            generation_json(reply="Have a good day!"),
        ],
        grading=[
            mission_json(done=[("t1", "x"), ("t2", "y")]),
            mission_json(done=[]),
        ],
    )
    cleared_turn = (await _mission(client, sid, {"text": "Coffee. How much?"})).json()
    assert cleared_turn["cleared"] is True  # 快判先顶 (两句话都词面命中)
    extra = await _mission(client, sid, {"text": "Thanks, you too!"})
    assert extra.status_code == 200 and extra.json()["cleared"] is True


# ============================================================ 累积合并 / 幂等


@pytest.mark.asyncio
async def test_same_utterance_twice_does_not_double_count_task(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        generation=[generation_json()],
        grading=[
            mission_json(done=[("t1", "a")]),
            mission_json(done=[("t1", "a")]),
            mission_json(done=[("t1", "a"), ("t2", "b")]),
        ],
    )
    first = (await _mission(client, sid, {"text": "Medium coffee please."})).json()
    await _grade(client, sid)
    repeat = (await _mission(client, sid, {"text": "Medium coffee please."})).json()
    await _grade(client, sid)
    third = (await _mission(client, sid, {"text": "How much total?"})).json()
    snapshot = await _grade(client, sid)
    assert first["newly_done"][0]["id"] == "t1"
    assert repeat["newly_done"] == [] and repeat["turn_index"] == 2  # 同句重说不重复打勾
    assert third["turn_index"] == 3 and third["cleared"] is True
    # 判分作业的合并同样是累积口径: 第 3 轮才认出来的 t2 落在**这一轮**的 turn_entry 上
    assert [item["id"] for item in _graded_entry(snapshot, 3)["newly_done"]] == ["t2"]


@pytest.mark.asyncio
async def test_task_completion_is_sticky_when_llm_walks_it_back(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """累积口径 (§5.5-2): 防误标后无法回退 —— LLM 翻供也不撤已打的勾."""
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        generation=[generation_json()],
        grading=[
            mission_json(done=[("t1", "ok")]),
            # 判分翻供: 说 t1 其实没完成 (而且还给了 5 分) —— 勾必须粘住, 分数照收。
            mission_json(done=[], grammar=5.0, vocabulary=5.0),
        ],
    )
    await _mission(client, sid, {"text": "Coffee please."})
    await _grade(client, sid)
    second = (await _mission(client, sid, {"text": "er"})).json()
    snapshot = await _grade(client, sid)
    assert second["checklist"][0]["done"] is True and second["newly_done"] == []
    assert _graded_entry(snapshot, 2)["sub_scores"]["grammar"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_hallucinated_task_ids_are_dropped(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        generation=[generation_json()],
        grading=[mission_json(done=[("t99", "不存在")])],
    )
    body = (await _mission(client, sid, {"text": "hi there."})).json()
    snapshot = await _grade(client, sid)
    assert body["newly_done"] == []
    assert [view["id"] for view in body["checklist"]] == ["t1", "t2", "t3"]
    assert [view["id"] for view in snapshot["mission"]["tasks"]] == ["t1", "t2", "t3"]


# ============================================================ 坏 JSON / D5


@pytest.mark.asyncio
async def test_bad_json_retries_once_then_uses_the_good_reply(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """台词侧的坏 JSON 仍然只回喂一次 (§A1: 两个函数共用 ``_judge`` 的这套纪律)."""
    sid = await _ready(client)
    fake = install_llm(
        monkeypatch,
        generation=["这不是 JSON", generation_json(reply="A medium coffee, coming up.")],
    )
    body = (await _mission(client, sid, {"text": "Medium coffee."})).json()
    assert len(fake.requests) == 2  # 初次 + 错误回喂重试一次
    assert body["reply"] == "A medium coffee, coming up." and body["llm_source"] == "qwen3.8-max"
    assert "上一条输出不合格" in str(fake.requests[1]["messages"][-1]["content"])


@pytest.mark.asyncio
async def test_second_bad_output_is_a_503_without_side_effects(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    """D5 (替代旧的"回放到剧本"用例): 两次都拿不到台词 -> **503 + 这一轮没有发生**.

    旧行为的代价有两层: ① 剧本回放从第 7 轮起永远同一句 (§0 根因); ② 它还冒充了一次
    不存在的生成 (``source="heuristic"`` 的台词看起来像模型说的)。新契约: 明说不可用,
    不落 turn、不落 step 行、不动任务清单、不出画像证据 —— "重发不重计"是这条断言的
    另一半 (学员重试一次成功后, 只会有一条 m1)。
    """
    sid = await _ready(client)
    fake = install_llm(monkeypatch, generation=["garbage one", "garbage two"])
    res = await _mission(client, sid, {"text": "Medium coffee with cream please."})
    assert res.status_code == 503
    err = res.json()["error"]
    assert err["code"] == "TURN_GENERATION_UNAVAILABLE" and "没有发生" in err["message"]
    # 与自由对话那条路由**同一份**码与文案 (工厂在 ``drill_grader``)。
    assert err["message"] == dg.turn_generation_unavailable().message
    assert len(fake.requests) == 2  # 只重试一次, 不做第三次

    snapshot = await _snapshot(client, sid)
    # 这一轮**一个字都没落**: mission 分区还是空的 (懒初始化只活在这次请求的内存里),
    # 所以任务清单没被推、判分指针也没被留下。
    assert snapshot["mission"] == {}
    assert snapshot["grading_status"] is None
    rows = (
        (await db.execute(select(PracticeStep).where(PracticeStep.session_id == sid)))
        .scalars()
        .all()
    )
    assert [row.step_id for row in rows if row.step_type == "mission_turn"] == []

    # 重发 (这次模型好了) -> 只计一轮
    install_llm(monkeypatch, generation=[generation_json()])
    retry = await _mission(client, sid, {"text": "Medium coffee with cream please."})
    assert retry.status_code == 200 and retry.json()["turn_index"] == 1
    rows2 = (
        (
            await db.execute(
                select(PracticeStep)
                .where(PracticeStep.session_id == sid, PracticeStep.step_type == "mission_turn")
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert [row.step_id for row in rows2] == ["m1"]


@pytest.mark.asyncio
async def test_no_llm_creds_is_a_503_and_writes_nothing(
    client: AsyncClient,
    scene_root: Path,
    db: AsyncSession,
) -> None:
    """本机/CI (只有 stub 凭据): D5 —— 实战轮直接 503, **不**回落到词面启发式台词.

    这是 §0 那条"7/8 轮降级"的正面契约: 宁可报错让学员重试, 也不拿剧本/目录里的下一句
    冒充模型生成。词面快判本身仍在 (它在**生成成功的轮次**里勾 checklist, 见 happy path),
    所以"启发式判定"这件事没有消失, 消失的只是"启发式台词"。
    """
    sid = await _ready(client)
    res = await _mission(client, sid, {"text": "A small coffee, please."})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "TURN_GENERATION_UNAVAILABLE"
    snapshot = await _snapshot(client, sid)
    assert snapshot["mission"] == {}
    orphan_events = (
        (await db.execute(select(AbilityEvent).where(AbilityEvent.step_id == "m1"))).scalars().all()
    )
    assert orphan_events == []


@pytest.mark.asyncio
async def test_heuristic_and_stub_evidence_never_creates_a_profile(
    client: AsyncClient, scene_root: Path, db: AsyncSession
) -> None:
    """§四 决策表的硬验收: 本机 (讯飞/LLM 都没 key) 画像永远不动."""
    sid = await _ready(client)
    await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    events = (await db.execute(select(AbilityEvent))).scalars().all()
    assert events  # 打基础的 stub/heuristic 证据全量进了流水 (审计)
    assert all(e.weight == 0.0 for e in events)
    assert (await db.execute(select(AbilityProfile))).scalars().all() == []


# ============================================================ max_turns 自动收工


@pytest.mark.asyncio
async def test_max_turns_cap_auto_finishes_with_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
) -> None:
    payload = make_course_dict()
    payload["briefing"] = BRIEFING6  # 与 _pass_briefing helper 的步骤清单一致
    mission = dict(payload["mission"])
    mission["max_turns"] = 4
    payload["mission"] = mission
    root = tmp_path / "scenes"
    root.mkdir(parents=True, exist_ok=True)
    (root / "scene_alpha.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()

    sid = await _ready(client)
    # 每轮都要有台词 (§A/D1: 拿不到就是 503); 不装 LLM 的话这条用例什么都测不到。
    spawns: list[str] = []
    monkeypatch.setattr(
        course_sessions, "spawn_mission_grading_job", lambda sid_: spawns.append(sid_) or True
    )
    install_llm(
        monkeypatch,
        generation=[generation_json(reply="Tell me more about that.")],
        grading=[mission_json(done=[])],
    )
    for i in range(1, 4):
        body = (await _mission(client, sid, {"text": f"turn number {i} content"})).json()
        assert body["auto_finished"] is False and body["review"] is None
    last = (await _mission(client, sid, {"text": "turn number four!"})).json()
    assert last["turn_count"] == 4 and last["auto_finished"] is True and last["finished"] is True
    assert last["stage"] == "review" and last["status"] == "completed"
    assert last["review"] is not None and last["review"]["auto_finished"] is True
    assert last["review"]["cleared"] is False  # 到顶未尽 -> 按未通关收口 (§5.1)
    # §A3: 每轮的判分作业都派生了 (四次), 最后那一轮也不例外 —— 否则"聊到轮次上限自然
    # 收工"这个最常见的结束方式会让最后一轮的润色/分数**永远**没人补。
    assert len(spawns) == 4
    assert last["grading_status"] == "pending"

    snapshot = await _snapshot(client, sid)
    assert snapshot["stage"] == "review" and snapshot["status"] == "completed"
    assert snapshot["review"]["session_id"] == sid
    # 判分作业跑完: 最后一轮的回填照样落 (报告数值是收工那一刻的快照, 逐轮明细走这里)。
    graded = await _grade(client, sid)
    assert graded["grading_status"] == "ready"
    assert _graded_entry(graded, 4)["grading"]["status"] == "ready"


# ============================================================ 音频输入 / 转写锚定 ISE


@pytest.mark.asyncio
async def test_audio_mission_without_iat_is_400(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    res = await _mission(client, sid, {"audio_b64": PCM_B64})
    assert res.status_code == 400 and res.json()["error"]["code"] == "TRANSCRIPT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mission_without_any_input_is_400(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    res = await _mission(client, sid, {})
    assert res.status_code == 400 and res.json()["error"]["code"] == "MISSION_INPUT_REQUIRED"


@pytest.mark.asyncio
async def test_audio_mission_uses_transcription_and_text_wins_over_audio(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    iat = FakeIAT("A small coffee to go.")
    monkeypatch.setattr(dg, "_IAT", iat)
    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    by_audio = (await _mission(client, sid, {"audio_b64": PCM_B64})).json()
    assert by_audio["transcript"] == "A small coffee to go."
    both = (await _mission(client, sid, {"audio_b64": PCM_B64, "text": "typed answer"})).json()
    assert both["transcript"] == "typed answer"
    assert iat.calls == 1  # 文本优先时不再浪费 IAT


@pytest.mark.asyncio
async def test_transcript_anchored_ise_produces_pronunciation_evidence(
    client: AsyncClient,
    scene_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """§5.4: 自由产出的发音证据 = 以**转写为参考文本**的 ISE (transcript_anchored)."""
    monkeypatch.setattr(dg, "_IAT", FakeIAT("A small coffee please."))
    sid = await _ready(client)  # 先开局: 打基础仍走 stub (凭据还没配)
    install_llm(monkeypatch, generation=[generation_json()])
    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    monkeypatch.setattr(me, "_ISE", FakeASR(scores=88.0))
    body = (await _mission(client, sid, {"audio_b64": PCM_B64})).json()
    assert body["sub_scores"]["pronunciation"] == pytest.approx(88.0)
    assert body["word_details"] and body["speech_rate_wpm"]
    pron = next(e for e in body["ability_events"] if e["dimension"] == "pronunciation")
    assert pron["ise_ref_mode"] == "transcript_anchored" and pron["weight"] == 1.0
    fluency = next(e for e in body["ability_events"] if e["dimension"] == "fluency")
    assert fluency["source"] == "xunfei"  # ISE fluency + wpm 综合的口径 (score_read_along)
    step = (
        await db.execute(
            select(PracticeStep).where(PracticeStep.session_id == sid, PracticeStep.step_id == "m1")
        )
    ).scalar_one()
    assert step.ise_ref_mode == "transcript_anchored"
    assert step.score_pronunciation == pytest.approx(88.0)
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.pronunciation == pytest.approx(88.0)


@pytest.mark.asyncio
async def test_anchored_evidence_dropped_when_ise_falls_back_to_stub(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    """讯飞配了但调用失败回退 StubASR: 证据整体丢弃 —— 宁可发音空缺, 不造假."""
    monkeypatch.setattr(dg, "_IAT", FakeIAT("A small coffee please."))
    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    monkeypatch.setattr(me, "_ISE", FakeASR(scores=95.0, source="stub"))
    body = (await _mission(client, sid, {"audio_b64": PCM_B64})).json()
    assert body["sub_scores"]["pronunciation"] is None and body["word_details"] == []
    assert [e for e in body["ability_events"] if e["dimension"] == "pronunciation"] == []
    # 锚定轮自身: m1 一条事件都不产 (无文本输入时语法/词汇也无 LLM 证据可给)
    turn_events = (
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id == "m1"
                )
            )
        )
        .scalars()
        .all()
    )
    assert turn_events == []


# ============================================================ hint


@pytest.mark.asyncio
async def test_hint_marks_next_turn_costs_score_without_judging(
    client: AsyncClient, scene_root: Path, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    hint = await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})
    assert hint.status_code == 200, hint.text
    payload = hint.json()
    assert payload["hint"]["task_id"] == "t1" and payload["costs_score"] is True
    assert payload["hint"]["hint_en"] == "A small coffee, please."
    assert payload["hints_used"] == 1

    turn = (await _mission(client, sid, {"text": "hi."})).json()
    assert turn["costs_score"] is True  # 只标记**下一个**判定回合
    follow = (await _mission(client, sid, {"text": "and then?"})).json()
    assert follow["costs_score"] is False  # 一次 hint 只欠一次

    rows = (
        (
            await db.execute(
                select(PracticeStep)
                .where(PracticeStep.session_id == sid)
                .order_by(PracticeStep.step_index)
            )
        )
        .scalars()
        .all()
    )
    mission_rows = [r for r in rows if r.step_type == "mission_turn"]
    assert [r.step_id for r in mission_rows] == ["m1", "m2"]
    assert mission_rows[0].annotated_json["costs_score"] is True
    assert mission_rows[1].annotated_json["costs_score"] is False

    await _finish(client, sid)
    # hints_used 是确定性字段, 202 的骨架里就有 (不必等文案作业)。
    assert (await _report(client, sid, run_copy_job=False))["hints_used"] == 1


@pytest.mark.asyncio
async def test_hint_when_all_tasks_done_falls_back_to_script(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    partial = (await _mission(client, sid, {"text": "A small coffee, please."})).json()
    # t1 完成了, 但 t2/t3 还开着 -> 提示仍指向第一个未完成任务
    hint1 = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert hint1["hint"]["task_id"] == "t2"
    await _mission(client, sid, {"text": "How much is that?"})
    await _mission(client, sid, {"text": "Thanks, have a good day."})
    assert partial["turn_index"] == 1
    hint2 = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert hint2["hint"]["task_id"] is None
    assert hint2["hint"]["script_line"]  # 全部任务完成: 回落剧本 B 行


@pytest.mark.asyncio
async def test_hint_and_checklist_expose_library_chinese(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7' 透出: 库内已有的双语进响应 —— MissionTaskView.hint_cn / hint_cn / script_line_cn."""
    cn_by_task = {"t1": "先说要一杯咖啡。", "t2": "记得把价格问出来。", "t3": "走之前道个别。"}
    course = make_course_dict("scene_alpha", "daily", briefing=BRIEFING6)
    tasks = [
        dict(task, hint_cn=cn_by_task[f"t{i}"])
        for i, task in enumerate(course["mission"]["tasks"], 1)
    ]
    write_course(
        scene_root,
        "scene_alpha",
        "daily",
        briefing=BRIEFING6,
        mission={**course["mission"], "tasks": tasks},
    )
    scene_store.invalidate_cache()

    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    body = (await _mission(client, sid, {"text": "A small coffee, please."})).json()
    by_id = {view["id"]: view for view in body["checklist"]}
    assert by_id["t1"]["hint_cn"] == "先说要一杯咖啡。"
    # add-only: 既有 checklist 键零变化.
    assert {"id", "desc_cn", "hint_en", "required", "done", "evidence", "done_at_turn"} <= set(
        by_id["t1"]
    )

    h = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert h["hint"]["task_id"] == "t2"
    assert h["hint"]["hint_cn"] == "记得把价格问出来。"
    assert h["hint"]["hint_en"] == "How much is that?"  # 既有字段原样
    assert {"task_id", "desc_cn", "hint_en", "script_line", "note_cn"} <= set(h["hint"])

    await _mission(client, sid, {"text": "How much is that?"})
    await _mission(client, sid, {"text": "Thanks, have a good day."})
    h2 = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    b_cn = {ex["b"]: ex["b_cn"] for ex in course["mission"]["exchanges"]}
    assert h2["hint"]["script_line"] in b_cn
    assert h2["hint"]["script_line_cn"] == b_cn[h2["hint"]["script_line"]]  # 回落带上 B 行中文

    await _finish(client, sid)
    report = await _report(client, sid, run_copy_job=False)
    assert {v["id"]: v["hint_cn"] for v in report["checklist"]} == cn_by_task


@pytest.mark.asyncio
async def test_hint_chinese_fields_empty_string_when_source_missing(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """库里没有中文时, 新字段是 "" 而不是 null / 缺键."""
    course = make_course_dict("scene_alpha", "daily", briefing=BRIEFING6)
    mission = {
        **course["mission"],
        "exchanges": [
            {k: v for k, v in ex.items() if k not in ("a_cn", "b_cn")}
            for ex in course["mission"]["exchanges"]
        ],
    }
    write_course(scene_root, "scene_alpha", "daily", briefing=BRIEFING6, mission=mission)
    scene_store.invalidate_cache()

    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    body = (await _mission(client, sid, {"text": "A small coffee, please."})).json()
    t1 = next(view for view in body["checklist"] if view["id"] == "t1")
    assert "hint_cn" in t1 and t1["hint_cn"] == ""

    h = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert "hint_cn" in h["hint"] and h["hint"]["hint_cn"] == ""

    await _mission(client, sid, {"text": "How much is that?"})
    await _mission(client, sid, {"text": "Thanks, have a good day."})
    h2 = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert "script_line_cn" in h2["hint"] and h2["hint"]["script_line_cn"] == ""
    assert h2["hint"]["script_line"]  # 既有回落素材不受影响


@pytest.mark.asyncio
async def test_legacy_snapshot_without_hint_cn_still_serves_hints_and_checklist(
    client: AsyncClient,
    scene_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """**存量会话**回归 (T2 质量审查记的坑): 老快照的任务里**没有** ``hint_cn`` 键.

    库里躺着一堆升级前开的局 (T2 之前 ``initial_task_states`` 不写这个键)。它们请求提示与
    checklist 必须照常工作: 缺键 -> ``""``, **不** 500、不 404。新字段的 add-only 承诺
    只有在"老数据也能读"时才算数。
    """
    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    assert (await _mission(client, sid, {"text": "hi there."})).status_code == 200

    row = (
        await db.execute(
            select(course_sessions.PracticeSession)
            .where(course_sessions.PracticeSession.id == sid)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    doc = copy.deepcopy(dict(row.doc))
    for task in doc["mission"]["tasks"]:
        task.pop("hint_cn", None)  # 模拟存量快照
    row.doc = doc
    await db.commit()

    hint = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert "hint_cn" in hint["hint"] and hint["hint"]["hint_cn"] == ""
    assert hint["hint"]["hint_en"]  # 既有字段不受影响

    turn = await _mission(client, sid, {"text": "and then?"})
    assert turn.status_code == 200, turn.text
    checklist = turn.json()["checklist"]
    assert checklist and all(view["hint_cn"] == "" for view in checklist)


@pytest.mark.asyncio
async def test_hint_and_mission_blocked_after_finish(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(monkeypatch, generation=[generation_json()])
    await _mission(client, sid, {"text": "hi there."})
    await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    hint = await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})
    turn = await _mission(client, sid, {"text": "still talking"})
    assert hint.status_code == 409 and turn.status_code == 409


# ============================================================ 归属 / 身份 / 挂载


@pytest.mark.asyncio
async def test_mission_gate_board_is_distinguishable(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    thief = await client.post(
        f"/api/v1/sessions/{sid}/mission", json={"device_id": "dev-thief", "text": "hello!"}
    )
    missing = await client.post(
        "/api/v1/sessions/no-such-session/mission", json={"device_id": DEV, "text": "x"}
    )
    no_id = await client.post(f"/api/v1/sessions/{sid}/mission", json={"text": "x"})
    no_id_finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={})
    assert thief.status_code == 403 and thief.json()["error"]["code"] == "FORBIDDEN_SESSION"
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert no_id.status_code == 400 and no_id.json()["error"]["code"] == "IDENTITY_REQUIRED"
    assert no_id_finish.status_code == 400
    unknown_user = await client.post(
        f"/api/v1/sessions/{sid}/mission",
        json={"user_id": "00000000-0000-0000-0000-000000000000", "text": "x"},
    )
    assert unknown_user.status_code == 403  # 不认识的账号 = 别人的局 (同 T3 恢复端点)


@pytest.mark.asyncio
async def test_mission_endpoints_mounted_with_review_contract() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert {
        "/api/v1/sessions/{session_id}/mission",
        "/api/v1/sessions/{session_id}/hint",
        "/api/v1/sessions/{session_id}/finish-mission",
        "/api/v1/ability",
        "/api/v1/polish",
        "/api/v1/expressions",
    } <= set(paths)
    review = schema["components"]["schemas"]["ReviewReport"]["properties"]
    assert {
        "overall",
        "dims",
        "pronunciation_subs",
        "highlights",
        "improvements",
        "checklist",
        "transcript_pairs",
        "new_tokens",
        "ability_delta",
        "source",
    } <= set(review)
    turn_props = schema["components"]["schemas"]["MissionTurnResponse"]["properties"]
    assert {"newly_done", "checklist", "sub_scores", "polish", "review", "cleared"} <= set(
        turn_props
    )

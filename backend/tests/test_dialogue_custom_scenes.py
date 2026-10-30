"""自定义对话场景**端点面** (§3 C3/C3b) —— 202 入口、job 轮询、目录合并与 turn/generate 链路.

覆盖:

* ``POST /dialogue/scenes/custom``: **校验同步、LLM 移出请求** —— 202 形状照
  ``scenes.GenerateAccepted`` (只有 ``job_id + polling_url``), 派生交给
  ``spawn_scene_brief_job`` (conftest 已 autouse no-op, spawn 记调用);
  长度/身份三道门在落 job 行之前挡下 (422 / 400 / 404, 不落半行)。
* **既有轮询端点复用**: 同一张 ``generation_jobs`` 由 ``kind`` 区分 ——
  ``JobView.kind="scene_brief"``, 终态 ready 的 ``scene_id`` 就是 ``custom_<行 id>``;
  别人的 job 403、未知 job 404 (既有纪律)。**不新增轮询端点** (§3 C3 原话: 作业面
  复用同一张 job 表, 只在 ``JobView`` 里多带 kind)。
* **目录合并 (轮询展示面)**: ``GET /dialogue/scenes`` 带身份追加 ``kind="custom"`` 行
  (仅 ready 态), 无身份与陌生身份只看到目录; ``default_scene`` 仍锚目录第一条。
* **202 -> job -> ready -> turn/generate 用 custom id** 的全链路 (形状路由: 作业吃
  ``scene=`` 队列, 台词吃 ``generation=`` 队列, 不依赖调用顺序); 素材 (persona/beats/goal)
  真的进了台词 prompt。
* **归属与 404** (§3 C3b 删兜底): 乱拼 id / 别人的 custom id / 无身份的 custom id 在
  turn 与 generate 上都 404 ``SCENE_NOT_FOUND``, 不再静默开成「商务会议」。
* **跨方言审计标签**: ``ability_events.step_id`` 是 varchar(32) 而 custom id 43 字符,
  ``_persist_turn_evidence`` 落库前截断 —— sqlite 宽容、PG 强校验, 测试绿不等于生产不炸。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import DialogueSceneRow, GenerationJob
from app.models.scene_spec import custom_scene_id
from app.services import scene_spec_generator as sg
from app.services.users import lookup_user
from tests.test_drill_grader import install_llm
from tests.test_scene_brief import scene_spec_json, scene_spec_payload

DEV = "dev-cust"
OTHER = "dev-other-cust"


async def _user_id(db: AsyncSession, device_id: str) -> str:
    user = await lookup_user(db, device_id=device_id, create=True)
    assert user is not None
    await db.commit()
    return user.id


async def _seed_ready_custom(db: AsyncSession, device: str, **over: Any) -> str:
    """种一行归属 ``device`` 的 ready 自定义场景 (作业终态本身在 test_scene_brief 钉)."""
    uid = await _user_id(db, device)
    row = DialogueSceneRow(
        user_id=uid,
        scene_key=f"manual-{device}-{over.get('title', 'x')}",
        doc=scene_spec_payload(**over),
        status="ready",
    )
    db.add(row)
    await db.commit()
    return custom_scene_id(row.id)


async def _post_custom(client: AsyncClient, **over: Any) -> Any:
    payload: dict[str, Any] = {"device_id": DEV, "scene_brief": "和外教聊我的周末"}
    payload.update(over)
    return await client.post("/api/v1/dialogue/scenes/custom", json=payload)


async def _job(client: AsyncClient, job_id: str, device: str | None = DEV) -> Any:
    params = {"device_id": device} if device is not None else {}
    return await client.get(f"/api/v1/scenes/jobs/{job_id}", params=params)


# ============================================================ POST (202, 同步校验)


@pytest.mark.asyncio
async def test_post_custom_returns_202_and_queues_job(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 不进请求 (§3 C3): 只建 kind=scene_brief 的 job 行 + spawn, 202 形状照 GenerateAccepted."""
    spawned: list[str] = []
    monkeypatch.setattr(sg, "spawn_scene_brief_job", spawned.append)
    r = await _post_custom(client)
    assert r.status_code == 202, r.text
    body = r.json()
    assert set(body) == {"job_id", "polling_url"}
    assert body["polling_url"] == f"/api/v1/scenes/jobs/{body['job_id']}"
    assert spawned == [body["job_id"]]

    job = await db.get(GenerationJob, body["job_id"])
    assert job is not None
    await db.refresh(job)
    assert job.status == "running"
    assert job.kind == "scene_brief"
    assert job.goal_text == "和外教聊我的周末"


@pytest.mark.asyncio
async def test_post_custom_entry_validation(client: AsyncClient) -> None:
    """长度门 422 / 无身份 400 / 未知 user_id 404 —— 都发生在建 job 行之前."""
    assert (await _post_custom(client, scene_brief="聊")).status_code == 422
    no_identity = await _post_custom(client, device_id=None)
    assert no_identity.status_code == 400
    assert no_identity.json()["error"]["code"] == "IDENTITY_REQUIRED"
    assert (
        await _post_custom(client, device_id=None, user_id="u-does-not-exist")
    ).status_code == 404


# ============================================================ 轮询端点 (kind 区分)


@pytest.mark.asyncio
async def test_scene_brief_job_visible_on_polling_endpoint(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既有 ``GET /scenes/jobs/{id}`` 通吃两种 kind: ready 的 scene_brief 带 ``custom_`` id."""
    uid = await _user_id(db, DEV)
    job = GenerationJob(
        user_id=uid,
        kind="scene_brief",
        goal_text="和外教聊我的周末",
        status="running",
        progress=0.0,
        stage_text="排队中…",
    )
    db.add(job)
    await db.commit()
    install_llm(monkeypatch, scene=[scene_spec_json()])
    await sg.run_scene_brief_job(job.id)

    view = (await _job(client, job.id, device=DEV)).json()
    assert view["kind"] == "scene_brief"
    assert view["status"] == "ready"
    assert str(view["scene_id"]).startswith("custom_")
    # 别人的 job 403, 未知 job 404 (既有纪律对新 kind 同样成立)。
    assert (await _job(client, job.id, device=OTHER)).status_code == 403
    assert (await _job(client, "job-not-there")).status_code == 404


@pytest.mark.asyncio
async def test_course_job_view_keeps_default_kind(client: AsyncClient, db: AsyncSession) -> None:
    """add-only: 整课作业 (不填 kind) 轮询响应照旧 ``kind="course"``。"""
    uid = await _user_id(db, DEV)
    legacy = GenerationJob(user_id=uid, goal_text="整课", status="running")
    db.add(legacy)
    await db.commit()
    view = (await _job(client, legacy.id)).json()
    assert view["kind"] == "course"


# ============================================================ 目录合并 (轮询展示面)


@pytest.mark.asyncio
async def test_list_dialogue_scenes_merges_ready_custom_only_for_owner(
    client: AsyncClient, db: AsyncSession
) -> None:
    """带身份 = 目录 + 自己的 ready 自定义 (kind/title/description 来自骨架); 别人与匿名只看目录。"""
    scene_id = await _seed_ready_custom(db, DEV, title="我的周末局")
    mine = (await client.get("/api/v1/dialogue/scenes", params={"device_id": DEV})).json()
    customs = [s for s in mine["scenes"] if s["kind"] == "custom"]
    assert [s["id"] for s in customs] == [scene_id]
    assert customs[0]["title"] == "我的周末局"
    # 英文出口 (I-2): 两个分支走同一份 DTO, 键都在; 目录行有 B6 的英文对, 自定义行**故意**
    # 为空 —— 学员自己写的中文描述没有英文对, 空串 = 那一行不渲染 (D5, 绝不机翻占位)。
    for scene in mine["scenes"]:
        assert "title_en" in scene and "description_en" in scene, scene["id"]
    assert all(
        s["title_en"].strip() and s["description_en"].strip()
        for s in mine["scenes"]
        if s["kind"] == "catalog"
    )
    assert customs[0]["title_en"] == "" and customs[0]["description_en"] == ""

    theirs = (await client.get("/api/v1/dialogue/scenes", params={"device_id": OTHER})).json()
    assert [s for s in theirs["scenes"] if s["kind"] == "custom"] == []

    anon = (await client.get("/api/v1/dialogue/scenes")).json()
    assert all(s["kind"] == "catalog" for s in anon["scenes"])
    # default_scene 锚死目录第一条: 某个学员的自定义场景不能变成全站默认。
    assert anon["default_scene"] == anon["scenes"][0]["id"]
    assert not anon["default_scene"].startswith("custom_")


@pytest.mark.asyncio
async def test_custom_scene_not_listed_until_ready(client: AsyncClient, db: AsyncSession) -> None:
    """只有 ready 行进口录: generating 的行是"还在路上", 不是"可用的场景"。"""
    uid = await _user_id(db, DEV)
    ghost = DialogueSceneRow(
        user_id=uid, scene_key="not-ready-yet", doc=scene_spec_payload(), status="generating"
    )
    db.add(ghost)
    await db.commit()
    mine = (await client.get("/api/v1/dialogue/scenes", params={"device_id": DEV})).json()
    assert [s for s in mine["scenes"] if s["kind"] == "custom"] == []


# ============================================================ turn / generate 用 custom id


@pytest.mark.asyncio
async def test_custom_scene_opens_a_thread_and_drives_a_turn(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**202 -> job -> ready -> 用 custom id 开线程 -> 发一轮** 的全链路.

    旧形状是 ``/dialogue/generate`` 拿开场白 + ``/dialogue/turn`` 发一轮; 两条都被线程
    端点取代 —— 开场白现在是**会话里的语音气泡** (不再是一次性的展示料), 台词走
    ``POST /dialogue/threads/{id}/turn``。素材 (人设/议程/目标) 仍必须进 prompt。
    """
    sid = await _seed_ready_custom(db, DEV)

    opened = await client.post(
        "/api/v1/dialogue/threads", json={"scene_key": sid}, params={"device_id": DEV}
    )
    assert opened.status_code == 201, opened.text
    lines = [m for m in opened.json()["messages"] if m["kind"] == "line"]
    assert lines and lines[0]["text"] == "Hey! How was your weekend?", lines

    fake = install_llm(
        monkeypatch,
        generation=[
            json.dumps(
                {
                    "reply": "Nice! I went hiking. What about your family?",
                    "reply_cn": "真好! 我去徒步了。你家人怎么样?",
                    "suggestion": "They are great, thanks.",
                    "suggestion_cn": "他们都很好, 谢谢。",
                    "learner_cn": "",
                    "speaker": "r1",
                },
                ensure_ascii=False,
            )
        ],
    )
    thread_id = opened.json()["id"]
    turn = await client.post(
        f"/api/v1/dialogue/threads/{thread_id}/turn",
        json={"mode": "text", "text": "It was good"},
        params={"device_id": DEV},
    )
    assert turn.status_code == 200, turn.text
    assert turn.json()["messages"][1]["text"].startswith("Nice!")

    prompt = " ".join(str(m) for m in fake.requests[0]["messages"])
    assert "说说去了哪" in prompt  # beats
    assert "自然地聊自己的周末活动" in prompt  # goal


@pytest.mark.asyncio
async def test_unknown_or_foreign_scene_is_404_everywhere(
    client: AsyncClient, db: AsyncSession
) -> None:
    """删兜底回归 (§3 C3b / §9-5): 乱拼 id 与别人/无身份的 custom id 在两个入口都 404。"""
    sid = await _seed_ready_custom(db, DEV)

    bogus_open = await client.post(
        "/api/v1/dialogue/threads",
        json={"scene_key": "totally_bogus_scene"},
        params={"device_id": DEV},
    )
    assert bogus_open.status_code == 404
    assert bogus_open.json()["error"]["code"] == "SCENE_NOT_FOUND"

    # 归属隔离: 别人的 custom id 与"不存在"同形 (不泄露存在性)。
    thief = await client.post(
        "/api/v1/dialogue/threads", json={"scene_key": sid}, params={"device_id": OTHER}
    )
    assert thief.status_code == 404
    assert (
        await client.post("/api/v1/dialogue/generate", json={"scene": sid, "device_id": OTHER})
    ).status_code == 404
    # 没身份的 custom id: 归属不可证 = 不可用。
    assert (await client.post("/api/v1/dialogue/generate", json={"scene": sid})).status_code == 404


# ============================================================ step_id 跨方言截断

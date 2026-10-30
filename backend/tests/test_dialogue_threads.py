"""v3.0 会话线程端点 (方案 S2.3): 幂等开会话、列表、读取灭红点、归属 404、删除.

覆盖的是"一个场景一条会话"这套形状能不能信:

* **幂等**: 同一身份对同一场景二次 ``POST`` 必须拿回**同一条**线程, 且开场白不被
  重复落一遍 —— 不幂等的话用户每退回列表再点进来, 聊天里就多一叠开场气泡;
* **归属**: 别人的线程与不存在的线程给**同一个** 404 (不泄露存在性), 与
  ``dialogue_scenes`` 的既有纪律同形;
* **身份**: 会话是个人数据, 没有匿名态 —— 无 ``device_id``/``user_id`` 直接 400;
* **红点**: ``unread`` 数的是"没看过的角色台词", ``GET`` 一次就该灭;
* **语音条**: 开线程时开场白就地合成 (测试里 TTS 未配凭据 -> stub), 拿到 URL 就
  ``audio_pending=false``, 拿不到也只是 pending, **不影响 201**。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import thread_store
from app.services.users import lookup_user

DEV_A = "dev-thread-a"
DEV_B = "dev-thread-b"
SCENE = "restaurant"


def _q(device: str) -> dict[str, str]:
    return {"device_id": device}


async def _open(client: AsyncClient, device: str, scene: str = SCENE):
    return await client.post(
        "/api/v1/dialogue/threads", json={"scene_key": scene}, params=_q(device)
    )


async def test_open_thread_is_idempotent_and_keeps_one_copy_of_openings(
    client: AsyncClient,
) -> None:
    first = await _open(client, DEV_A)
    assert first.status_code == 201, first.text
    body = first.json()
    opening_count = sum(1 for m in body["messages"] if m["kind"] == thread_store.KIND_LINE)
    assert opening_count >= 2, body["messages"]

    second = await _open(client, DEV_A)
    assert second.status_code == 201, second.text
    again = second.json()
    assert again["id"] == body["id"], "同 owner + 同场景必须回到同一条线程"
    lines = [m for m in again["messages"] if m["kind"] == thread_store.KIND_LINE]
    assert len(lines) == opening_count, f"开场白被重复落库: {len(lines)} vs {opening_count}"


async def test_opened_thread_messages_have_monotonic_unique_ids(client: AsyncClient) -> None:
    """气泡 id 是 LazyColumn 的 key —— 重复 key 在 v2.3.0 崩过一次 (6fae05d)."""
    body = (await _open(client, DEV_A)).json()
    ids = [m["id"] for m in body["messages"]]
    assert len(ids) == len(set(ids)), ids
    seqs = [int(i[1:]) for i in ids]
    assert seqs == sorted(seqs), ids


async def test_opening_lines_carry_audio_or_soft_pending(client: AsyncClient) -> None:
    body = (await _open(client, DEV_A)).json()
    lines = [m for m in body["messages"] if m["kind"] == thread_store.KIND_LINE]
    for line in lines:
        # stub/真合成都该给出可播的绝对 URL; 唯一合法的缺音频形态是 pending。
        assert (line["audio_url"] is not None) or line["audio_pending"], line
        if line["audio_url"] is not None:
            assert line["audio_url"].startswith("http"), line["audio_url"]
            assert line["audio_ms"] > 0, line


async def test_open_thread_unknown_scene_404(client: AsyncClient) -> None:
    resp = await _open(client, DEV_A, scene="no_such_scene")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SCENE_NOT_FOUND"


async def test_threads_require_identity(client: AsyncClient) -> None:
    """建、读、删三条路都不许有匿名态 —— 会话是个人数据。"""
    resp = await client.post("/api/v1/dialogue/threads", json={"scene_key": SCENE})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "IDENTITY_REQUIRED"

    listed = await client.get("/api/v1/dialogue/threads")
    assert listed.status_code == 400
    assert listed.json()["error"]["code"] == "IDENTITY_REQUIRED"

    deleted = await client.delete("/api/v1/dialogue/threads/whatever")
    assert deleted.status_code == 400
    assert deleted.json()["error"]["code"] == "IDENTITY_REQUIRED"


async def test_list_threads_shows_preview_then_get_clears_unread(client: AsyncClient) -> None:
    thread = (await _open(client, DEV_A)).json()

    listed = (await client.get("/api/v1/dialogue/threads", params=_q(DEV_A))).json()
    assert [row["id"] for row in listed] == [thread["id"]]
    row = listed[0]
    assert row["scene_id"] == SCENE
    assert row["preview"], row
    assert row["unread"] >= 2, f"开场白还没看过, 红点该数到它们: {row}"

    opened = await client.get(f"/api/v1/dialogue/threads/{thread['id']}", params=_q(DEV_A))
    assert opened.status_code == 200

    after = (await client.get("/api/v1/dialogue/threads", params=_q(DEV_A))).json()[0]
    assert after["unread"] == 0, f"打开过就该灭: {after}"


async def test_list_threads_is_scoped_to_the_owner(client: AsyncClient) -> None:
    await _open(client, DEV_A)
    await _open(client, DEV_B, scene="coffee_shop")

    mine = (await client.get("/api/v1/dialogue/threads", params=_q(DEV_A))).json()
    theirs = (await client.get("/api/v1/dialogue/threads", params=_q(DEV_B))).json()
    assert {r["scene_id"] for r in mine} == {SCENE}
    assert {r["scene_id"] for r in theirs} == {"coffee_shop"}


async def test_other_owners_thread_and_unknown_thread_both_404(client: AsyncClient) -> None:
    thread_id = (await _open(client, DEV_A)).json()["id"]

    # 别人的行与不存在的行**同一个答案** —— 差别会泄露"这个 id 上有人聊过".
    intruder = await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV_B))
    missing = await client.get(
        "/api/v1/dialogue/threads/00000000-0000-0000-0000-000000000000", params=_q(DEV_A)
    )
    assert intruder.status_code == 404
    assert missing.status_code == 404
    assert intruder.json()["error"]["code"] == missing.json()["error"]["code"] == "THREAD_NOT_FOUND"


async def test_delete_thread_removes_only_that_thread(client: AsyncClient) -> None:
    first = (await _open(client, DEV_A)).json()["id"]
    await _open(client, DEV_A, scene="coffee_shop")

    assert (
        await client.delete(f"/api/v1/dialogue/threads/{first}", params=_q(DEV_A))
    ).status_code == 200
    remaining = (await client.get("/api/v1/dialogue/threads", params=_q(DEV_A))).json()
    assert [r["id"] for r in remaining] and first not in [r["id"] for r in remaining]

    gone = await client.get(f"/api/v1/dialogue/threads/{first}", params=_q(DEV_A))
    assert gone.status_code == 404


@pytest.mark.parametrize("kind", list(thread_store.MESSAGE_KINDS))
async def test_message_kinds_survive_the_round_trip(
    client: AsyncClient, db: AsyncSession, kind: str
) -> None:
    """四种气泡都能原样回读 —— doc 是客户端渲染的唯一真相, 走形一处 UI 就缺一块."""
    from app.services.dialogue_scenes import resolve_scene

    body = (await _open(client, DEV_A)).json()
    row = await thread_store.get_thread(db, body["id"], (await lookup_user(db, device_id=DEV_A)).id)
    doc = dict(row.doc)
    scene = resolve_scene(SCENE)
    thread_store.append_message(
        doc["messages"],
        scene,
        kind=kind,
        role_id=scene.roles[0].role_id if kind == thread_store.KIND_LINE else "",
        text=f"text-{kind}",
        text_cn=f"中文-{kind}",
        recognized_text="我说了什么" if kind == thread_store.KIND_USER else "",
    )
    assert await thread_store.save_doc(db, row, doc, turn_count=row.turn_count + 1)

    echoed = (await client.get(f"/api/v1/dialogue/threads/{body['id']}", params=_q(DEV_A))).json()
    last = echoed["messages"][-1]
    assert last["kind"] == kind
    assert last["text"] == f"text-{kind}"
    assert last["text_cn"] == f"中文-{kind}"


async def test_save_doc_persists_even_when_caller_mutated_the_orm_copy(
    client: AsyncClient, db: AsyncSession
) -> None:
    """回归锁: ``doc`` 列不许出现"半行更新" (turn_count 写了、消息还是旧的).

    浅拷贝 ``dict(row.doc)`` 会让调用方**就地**改掉 ORM 里那份旧值, 于是写回时新旧
    内容相等、SQLAlchemy 判定无变化、``doc`` 不进 UPDATE —— 症状是只写了一半。
    ``save_doc`` 里 ``flag_modified`` 是这道保险, :func:`thread_store.load_doc`
    是把坑绕过去的唯一入口; 这条用例钉住"就算调用方拿浅拷贝改, 也必须落库"。
    """
    from app.services.dialogue_scenes import resolve_scene

    body = (await _open(client, DEV_A)).json()
    uid = (await lookup_user(db, device_id=DEV_A)).id
    row = await thread_store.get_thread(db, body["id"], uid)
    before = len(thread_store.messages_of(row.doc))

    shallow = dict(row.doc)  # 故意用错的方式: 与 ORM 共享 messages 那个 list
    thread_store.append_message(
        shallow["messages"], resolve_scene(SCENE), kind=thread_store.KIND_USER, text="半行更新探针"
    )
    assert await thread_store.save_doc(db, row, shallow, turn_count=row.turn_count + 1)

    echoed = (await client.get(f"/api/v1/dialogue/threads/{body['id']}", params=_q(DEV_A))).json()
    assert len(echoed["messages"]) == before + 1, (
        f"doc 列没落库: 期望 {before + 1} 条, 实际 {len(echoed['messages'])} 条"
    )
    assert echoed["messages"][-1]["text"] == "半行更新探针"

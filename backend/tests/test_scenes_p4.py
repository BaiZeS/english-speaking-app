"""scenes P4 端点测试: 合并 (DB 优先) / 进度三字段变真 / 归属隔离 / DELETE 语义.

任务书 §范围 3 + §范围 5 的端点面:

* ``GET /scenes`` 画廊: DB 生成课与 curated 按 ``merge_courses`` 合并 (id 冲突
  DB 优先), 摘要 ``cleared`` / ``best_total`` / ``attempts`` 从 ``course_progress``
  读出 (T2 预告的「协议零改动, 值变真」); 坏 doc 行跳过 (T2 坏文件策略的 DB 版);
* ``GET /scenes/{id}`` / ``/script``: 生成课仅归属该 device 可见 (别人的 404);
* ``DELETE /scenes/{id}``: 只删 generated (curated -> 405, 别人的 -> 404);
* ``GET /courses/progress``: 物化直读, 身份必须。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import CourseProgressRow, SceneCourseRow, User
from app.services import scene_store
from tests.test_scene_store import make_course_dict, write_course

DEV = "dev-scenes-p4"
OTHER = "dev-other-p4"
GEN_ID = "scene_gtest0001"


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    scene_store.invalidate_cache()
    yield
    scene_store.invalidate_cache()


@pytest.fixture
def scene_root(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    write_course(tmp_path, "scene_alpha", "daily")
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path
    scene_store.invalidate_cache()


async def _seed_user(db: AsyncSession, device_id: str) -> User:
    user = User(device_id=device_id)
    db.add(user)
    await db.commit()  # 种子行必须落库: 请求会话在共享连接上, 未提交数据会被回滚
    return user


def _generated_doc(scene_id: str = GEN_ID, **over: Any) -> dict[str, Any]:
    doc = make_course_dict(scene_id, "daily", source="generated", goal_text="我想学会点咖啡")
    doc.update(over)
    return doc


async def _seed_generated(
    db: AsyncSession, user: User, doc: dict[str, Any] | None = None, *, status: str = "ready"
) -> SceneCourseRow:
    row = SceneCourseRow(
        user_id=user.id,
        scene_key=f"key-{doc['id'] if doc else GEN_ID}",
        doc=doc or _generated_doc(),
        status=status,
    )
    db.add(row)
    await db.commit()
    return row


# ============================================================ 画廊合并 + 进度


@pytest.mark.asyncio
async def test_gallery_merges_generated_and_curated(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user)

    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    by_id = {s["id"]: s for s in page["scenes"]}
    assert GEN_ID in by_id and by_id[GEN_ID]["source"] == "generated"
    assert "scene_alpha" in by_id and by_id["scene_alpha"]["source"] == "curated"
    # 没玩过: 三字段保持默认值但字段在场 (协议零改动)
    assert by_id[GEN_ID]["cleared"] is False
    assert by_id[GEN_ID]["best_total"] == 0.0
    assert by_id[GEN_ID]["attempts"] == 0

    # 不带身份: 生成课不可见 (归属者的私人内容)
    anon = (await client.get("/api/v1/scenes")).json()
    assert GEN_ID not in {s["id"] for s in anon["scenes"]}
    assert "scene_alpha" in {s["id"] for s in anon["scenes"]}


@pytest.mark.asyncio
async def test_gallery_id_conflict_db_wins(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user, _generated_doc("scene_alpha"))

    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    conflicts = [s for s in page["scenes"] if s["id"] == "scene_alpha"]
    assert len(conflicts) == 1  # 合并不是堆重复
    assert conflicts[0]["source"] == "generated"  # DB 优先 (curated 被覆盖)
    detail = await client.get("/api/v1/scenes/scene_alpha", params={"device_id": DEV})
    assert detail.json()["goal_text"] == "我想学会点咖啡"  # 内容也来自 DB 行


@pytest.mark.asyncio
async def test_gallery_progress_three_fields_turn_real(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user)
    db.add(
        CourseProgressRow(
            user_id=user.id,
            scene_id=GEN_ID,
            attempts=2,
            cleared=True,
            best_total=82.5,
            last_stage="review",
            last_session_id="sess-1",
            estimated_seconds=300.0,
        )
    )
    await db.commit()

    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    summary = next(s for s in page["scenes"] if s["id"] == GEN_ID)
    assert summary["cleared"] is True
    assert summary["best_total"] == 82.5
    assert summary["attempts"] == 2


@pytest.mark.asyncio
async def test_gallery_skips_corrupt_doc(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    # 两类坏行: doc 不是 JSON 对象 / doc 缺字段过不了模型校验 —— 都只跳过自己
    db.add(
        SceneCourseRow(user_id=user.id, scene_key="bad-list", doc=["not", "a dict"], status="ready")
    )
    db.add(
        SceneCourseRow(
            user_id=user.id, scene_key="bad-dict", doc={"not": "a course"}, status="ready"
        )
    )
    await db.commit()
    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    assert page["scenes"]  # curated 还在
    assert all(s["source"] == "curated" for s in page["scenes"])


# ============================================================ 详情 / 剧本归属


@pytest.mark.asyncio
async def test_generated_detail_visible_only_to_owner(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user)

    ok = await client.get(f"/api/v1/scenes/{GEN_ID}", params={"device_id": DEV})
    assert ok.status_code == 200 and ok.json()["source"] == "generated"

    thief = await client.get(f"/api/v1/scenes/{GEN_ID}", params={"device_id": OTHER})
    assert thief.status_code == 404  # 不泄露存在性

    anon = await client.get(f"/api/v1/scenes/{GEN_ID}")
    assert anon.status_code == 404

    curated = await client.get("/api/v1/scenes/scene_alpha", params={"device_id": DEV})
    assert curated.status_code == 200 and curated.json()["source"] == "curated"


@pytest.mark.asyncio
async def test_generated_script_projection(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user)
    res = await client.get(f"/api/v1/scenes/{GEN_ID}/script", params={"device_id": DEV})
    assert res.status_code == 200
    body = res.json()
    assert body["scene_id"] == GEN_ID and body["source"] == "generated"
    assert len(body["roles"][0]["lines"]) == len(body["roles"][1]["lines"])


@pytest.mark.asyncio
async def test_invalid_scene_id_is_still_400(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    res = await client.get("/api/v1/scenes/..%2Fetc", params={"device_id": DEV})
    assert res.status_code in (400, 404)


@pytest.mark.asyncio
async def test_detail_of_corrupt_generated_doc_is_404(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    """doc 过不了模型校验的生成课 = 详情 404 (坏内容不 500)."""
    user = await _seed_user(db, DEV)
    bad = {"id": GEN_ID, "category": "nope"}  # 有 id 能被找到, 但过不了 SceneCourse
    db.add(SceneCourseRow(user_id=user.id, scene_key="bad", doc=bad, status="ready"))
    await db.commit()
    res = await client.get(f"/api/v1/scenes/{GEN_ID}", params={"device_id": DEV})
    assert res.status_code == 404


# ============================================================ DELETE 语义


@pytest.mark.asyncio
async def test_delete_curated_is_405(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    res = await client.delete("/api/v1/scenes/scene_alpha", params={"device_id": DEV})
    assert res.status_code == 405 and res.json()["error"]["code"] == "CURATED_SCENE_READONLY"


@pytest.mark.asyncio
async def test_delete_own_generated_course(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user)
    res = await client.delete(f"/api/v1/scenes/{GEN_ID}", params={"device_id": DEV})
    assert res.status_code == 204
    assert (
        await client.get(f"/api/v1/scenes/{GEN_ID}", params={"device_id": DEV})
    ).status_code == 404
    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    assert GEN_ID not in {s["id"] for s in page["scenes"]}


@pytest.mark.asyncio
async def test_delete_other_generated_is_404(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    await _seed_generated(db, user)
    res = await client.delete(f"/api/v1/scenes/{GEN_ID}", params={"device_id": OTHER})
    assert res.status_code == 404
    assert (
        await client.get(f"/api/v1/scenes/{GEN_ID}", params={"device_id": DEV})
    ).status_code == 200


@pytest.mark.asyncio
async def test_delete_requires_identity(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    res = await client.delete(f"/api/v1/scenes/{GEN_ID}")
    assert res.status_code == 400 and res.json()["error"]["code"] == "IDENTITY_REQUIRED"


@pytest.mark.asyncio
async def test_delete_unknown_generated_scene_is_404(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    """身份有效但查无此生成课 (含 curated 里也没有的 id) -> 404."""
    await _seed_user(db, DEV)
    res = await client.delete("/api/v1/scenes/scene_nope", params={"device_id": DEV})
    assert res.status_code == 404 and res.json()["error"]["code"] == "SCENE_NOT_FOUND"


# ============================================================ GET /courses/progress


@pytest.mark.asyncio
async def test_courses_progress_endpoint(
    client: AsyncClient, db: AsyncSession, scene_root: Any
) -> None:
    user = await _seed_user(db, DEV)
    db.add(
        CourseProgressRow(
            user_id=user.id,
            scene_id=GEN_ID,
            attempts=1,
            cleared=False,
            best_total=55.0,
            last_stage="review",
            last_session_id="sess-9",
            estimated_seconds=90.0,
        )
    )
    await db.commit()

    res = await client.get("/api/v1/courses/progress", params={"device_id": DEV})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["progress"][0]
    assert item["scene_id"] == GEN_ID
    assert item["attempts"] == 1 and item["cleared"] is False
    assert item["best_total"] == 55.0 and item["last_stage"] == "review"
    assert item["last_session_id"] == "sess-9" and item["estimated_seconds"] == 90.0

    # 没注册过的 device: 空列表, 不是 404 (首页照常渲染)
    empty = await client.get("/api/v1/courses/progress", params={"device_id": OTHER})
    assert empty.status_code == 200 and empty.json() == {"total": 0, "progress": []}

    # 身份必须
    missing = await client.get("/api/v1/courses/progress")
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "IDENTITY_REQUIRED"

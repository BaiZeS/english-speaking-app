"""Tests for the /api/v1/dialogue/scenes endpoint + dialogue_scenes module."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import User
from app.services import dialogue_scenes

#: 身份注册用例的 device id (T4 I-1 回归; 每个用例一张全新内存库, 不与别处相撞)。
DEV = "dev-generate-registers"


def _ascii_letter_ratio(text: str) -> float:
    """字母里 ASCII 字母的占比 (中文 0.0 / 英文 1.0) —— "英文侧抄成中文"也能被这条抓住."""
    letters = [ch for ch in text if ch.isalpha()]
    return sum(ch.isascii() for ch in letters) / len(letters) if letters else 0.0


@pytest.mark.asyncio
async def test_dialogue_scenes_endpoint_returns_catalog(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/dialogue/scenes")
    assert r.status_code == 200
    data = r.json()
    assert "scenes" in data
    assert "default_scene" in data
    assert len(data["scenes"]) >= 4  # we ship at least the original 4 scenes
    # Default should be the first scene in the catalog.
    assert data["default_scene"] == data["scenes"][0]["id"]


@pytest.mark.asyncio
async def test_dialogue_scenes_ids_match_catalog(client: httpx.AsyncClient) -> None:
    listed_ids = {s["id"] for s in (await client.get("/api/v1/dialogue/scenes")).json()["scenes"]}
    catalog_ids = {s.id for s in dialogue_scenes.list_scenes()}
    assert listed_ids == catalog_ids


def test_list_scenes_returns_at_least_four() -> None:
    assert len(dialogue_scenes.list_scenes()) >= 4


def test_resolve_scene_known_returns_matching_scene() -> None:
    scene = dialogue_scenes.resolve_scene("ordering_coffee")
    assert scene is not None and scene.id == "ordering_coffee"
    assert scene.opening
    assert scene.suggestion
    # §A4/D5: 那两个"LLM 拿不到就照本宣科"的兜底字段已删, 这里钉住它们**没被加回来**;
    # §3 B6 新加的 openings/suggestions 素材字段不许顺着旧缝复活成兜底 (见下面素材用例)。
    assert not hasattr(scene, "next_suggestion") and not hasattr(scene, "fallback_reply")
    assert not hasattr(dialogue_scenes, "get_scene")


def test_resolve_scene_unknown_returns_none() -> None:
    """§3 C3b 删兜底回归: 拼错的 id **不再**静默回落到目录第一条 (那会教成「商务会议」)。"""
    assert dialogue_scenes.resolve_scene("__nonexistent__") is None
    # "custom_" 前缀不是目录 id —— 归属解析只活在 ``api/v1/dialogue`` 的 DB 接缝里。
    assert dialogue_scenes.resolve_scene("custom_0f2ab7c1-0000-4000-8000-000000000000") is None


def test_scene_catalog_only_contains_unique_ids() -> None:
    ids = [s.id for s in dialogue_scenes.list_scenes()]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_dialogue_scenes_payload_shape(client: httpx.AsyncClient) -> None:
    """不带身份 = 目录形状 + add-only 的 ``kind="catalog"`` (旧 APK 多键不炸)."""
    r = await client.get("/api/v1/dialogue/scenes")
    scene = r.json()["scenes"][0]
    for field in ("id", "title", "description", "kind", "title_en", "description_en"):
        assert field in scene, f"missing {field}"
    assert scene["kind"] == "catalog"


@pytest.mark.asyncio
async def test_dialogue_scenes_expose_english_display_pair(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    """I-2: 场景选择器要「中文 + 英文并列」—— 目录行的英文对必须到 API 边界。

    带不带身份都拿得到 (身份只影响是否**追加**自定义场景, 不改目录行的形状), 而且读侧
    零建行: 陌生 device 读一次列表不该把自己注册进 users (注册口径只在写侧)。
    """
    anon = (await client.get("/api/v1/dialogue/scenes")).json()
    identified = (
        await client.get("/api/v1/dialogue/scenes", params={"device_id": "dev-scenes-en"})
    ).json()
    for payload in (anon, identified):
        assert payload["scenes"], "目录不该是空的"
        for scene in payload["scenes"]:
            assert scene["title_en"].strip() and scene["description_en"].strip(), scene["id"]
            # 成对性: 英文侧不是把中文抄一遍 (只查非空的话抄成中文也能过)。
            assert scene["title_en"] != scene["title"], scene["id"]
    assert (await db.execute(select(User))).scalars().all() == []


def test_catalog_scenes_carry_full_prompt_material_b6() -> None:
    """§3 B6 九场景扩容: 素材字段全员到位 (dataclass 已删默认值, 漏填直接构造 TypeError).

    钉的是**下限与锚点**而不是内容本身: beats 3-6 条、开场候补 ≥2 (含旧 ``opening``,
    选择器播的那句永远可以再多一句)、示范素材 ≥2 (含旧 ``suggestion``)、英文展示对非空。

    成对性 (M-5): 只断"非空"的话, 把中文抄进 ``title_en`` 也能过 —— 那是"英文字段"
    名存实亡; 中文标题 + 英文展示对是两个字段的**成对**契约, 所以这里同时断
    ``title_en != title`` 与英文素材的 ASCII 字母占比 (中文占比 0.0, 一眼抓出)。
    """
    scenes = dialogue_scenes.list_scenes()
    assert {s.id for s in scenes} == {
        "business_meeting",
        "work_report",
        "negotiation",
        "daily_conversation",
        "ordering_coffee",
        "job_interview",
        "travel",
        "shopping",
        "doctor",
    }
    for scene in scenes:
        assert scene.title_en.strip() and scene.description_en.strip(), scene.id
        assert scene.title_en != scene.title, scene.id
        assert scene.description_en != scene.description, scene.id
        assert scene.persona.strip() and scene.user_role.strip(), scene.id
        assert 3 <= len(scene.beats) <= 6, scene.id
        assert len(scene.openings) >= 2, scene.id
        assert scene.opening in scene.openings
        assert len(scene.suggestions) >= 2, scene.id
        assert scene.suggestion in scene.suggestions
        # 学员要开口说的那几句必须是英文 (0.6 留出标点/连字符的余地, 中文是 0.0)。
        for line in (*scene.openings, *scene.suggestions):
            assert _ascii_letter_ratio(line) >= 0.6, (scene.id, line)


def test_scene_messages_consumes_persona_beats_and_material() -> None:
    """扩容素材必须**有消费者** (否则 B6 只是一堆进不了 prompt 的死数据, §A5 的初衷)."""
    from app.api.v1 import dialogue

    scene = dialogue_scenes.resolve_scene("business_meeting")
    assert scene is not None
    system = str(dialogue._scene_messages(scene, [], [])[0].content)
    assert scene.persona in system and scene.user_role in system
    tail = str(dialogue._scene_messages(scene, [], [])[-1].content)
    for beat in scene.beats:
        assert beat in tail
    for line in scene.suggestions:
        assert line in tail
    # 参考句素材的**取材**措辞 (不是台本): 显式禁令在 prompt 里。
    assert "不许原样复述" in tail
    # openings 是开场白 (generate) 的素材, 不进台词 prompt —— 台词没有"开场"可言。
    assert scene.openings[0] not in system


def test_opening_prompt_carries_persona_and_alternates() -> None:
    """``/dialogue/generate`` 的 LLM 分支同样吃素材: 人设 + **≥2 开场候补**都进 prompt."""
    from app.api.v1 import dialogue

    scene = dialogue_scenes.resolve_scene("business_meeting")
    assert scene is not None
    joined = "\n".join(str(m.content) for m in dialogue._opening_prompt(scene))
    assert scene.persona in joined
    for opening in scene.openings:
        assert opening in joined
    # 措辞纪律: 候选是"自己改写"的素材, 不是播第一句的台本。
    assert "never quote verbatim" in joined


# ============================================================ 身份注册 (写侧落 commit)


@pytest.mark.asyncio
async def test_generate_registers_new_device_identity(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    """I-1 回归: ``POST /dialogue/generate`` 承诺的 device 注册必须**落库**。

    handler 收 ``device_id`` 就经 :func:`dialogue._identity_user` 找/建 User, 但
    ``deps.get_db`` 的会话**不自动 commit** —— 没有显式 commit 时, ``flush`` 出来的
    那一行随请求结束一起回滚 (探针: generate 之后新会话查 ``users`` 是 0 行)。
    写侧先例是 ``POST /history``: 建行的路由自己 commit。
    """
    res = await client.post(
        "/api/v1/dialogue/generate", json={"scene": "ordering_coffee", "device_id": DEV}
    )
    assert res.status_code == 200, res.text
    rows = (await db.execute(select(User).where(User.device_id == DEV))).scalars().all()
    assert [row.device_id for row in rows] == [DEV]


@pytest.mark.asyncio
async def test_generate_without_identity_writes_no_user(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    """不带身份 = 旧客户端的纯无状态行为: 零建行 (注册口径只对显式给身份的请求生效)。"""
    res = await client.post("/api/v1/dialogue/generate", json={"scene": "ordering_coffee"})
    assert res.status_code == 200, res.text
    assert (await db.execute(select(User))).scalars().all() == []

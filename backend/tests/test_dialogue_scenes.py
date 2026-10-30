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

#: v3.0 目录的 12 场 (S2.2), 按目录顺序钉死 —— ``default_scene`` 取第一条, 顺序也是契约。
#: id 一旦发布不许改: 它会写进存量会话线程。
CATALOG_IDS: tuple[str, ...] = (
    "restaurant",
    "coffee_shop",
    "airport_checkin",
    "hotel_checkin",
    "doctor",
    "rental",
    "shopping",
    "asking_directions",
    "pickup",
    "small_talk",
    "team_meeting",
    "work_report",
)


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
    assert len(data["scenes"]) == 12
    # Default should be the first scene in the catalog.
    assert data["default_scene"] == data["scenes"][0]["id"] == "restaurant"


@pytest.mark.asyncio
async def test_dialogue_scenes_ids_match_catalog(client: httpx.AsyncClient) -> None:
    listed_ids = {s["id"] for s in (await client.get("/api/v1/dialogue/scenes")).json()["scenes"]}
    catalog_ids = {s.id for s in dialogue_scenes.list_scenes()}
    assert listed_ids == catalog_ids


def test_list_scenes_returns_exactly_twelve() -> None:
    """目录恰好 12 场、顺序钉死 (S2.2 的十二场, 一场不多一场不少)。"""
    scenes = dialogue_scenes.list_scenes()
    assert len(scenes) == 12
    assert tuple(s.id for s in scenes) == CATALOG_IDS


def test_resolve_scene_known_returns_matching_scene() -> None:
    scene = dialogue_scenes.resolve_scene("coffee_shop")
    assert scene is not None and scene.id == "coffee_shop"
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


def test_voices_match_the_tts_known_voices() -> None:
    """``VOICES`` 与 ``mimo_tts._KNOWN_VOICES`` 同源钉死 (dialogue_scenes.py 头注的承诺)。

    目录里出现一个 TTS 侧不认识的音色 = 合成时静默回落默认音色, 群聊"听不出是谁在说"
    的防线就塌了; 加音色必须两处一起加。
    """
    from app.services import mimo_tts

    assert set(dialogue_scenes.VOICES) == set(mimo_tts._KNOWN_VOICES)


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


def test_every_scene_carries_roles_voices_and_material() -> None:
    """v3.0 群聊素材 (S2.2): 逐场钉死多角色形状, 漏一条就红。

    * ``roles`` 2-3 个, ``role_id`` 依序 r1/r2/r3, 音色 ∈ ``VOICES`` 且**场内不重复**
      (重复就听不出是谁在说), 名字与人设中英两格齐;
    * ``opening_lines`` ≥2, 每条的 ``role_id`` 必须被 :meth:`role_of` **精确命中** ——
      命中不了就是 bug, 不许回落第一个角色 (``role_of`` 对未知 id 返回 ``None``);
    * ``suggestion_lines`` ≥2、``beats`` 3-6 条;
    * 中英展示格 (title/description/user_role 及每条 line 的两格) 全部非空白,
      英文格还得真是英文 (M-5 成对性: 只查非空的话, 抄成中文也能过)。
    """
    scenes = dialogue_scenes.list_scenes()
    assert {s.id for s in scenes} == set(CATALOG_IDS)
    for scene in scenes:
        for field in (
            scene.title,
            scene.title_en,
            scene.description,
            scene.description_en,
            scene.user_role,
            scene.user_role_en,
        ):
            assert field.strip(), (scene.id, field)
        assert _ascii_letter_ratio(scene.title_en) >= 0.6, scene.id
        assert _ascii_letter_ratio(scene.description_en) >= 0.6, scene.id
        assert _ascii_letter_ratio(scene.user_role_en) >= 0.6, scene.id

        assert 2 <= len(scene.roles) <= 3, (scene.id, len(scene.roles))
        assert [role.role_id for role in scene.roles] == [
            f"r{index}" for index in range(1, len(scene.roles) + 1)
        ], scene.id
        voices = [role.voice for role in scene.roles]
        assert all(voice in dialogue_scenes.VOICES for voice in voices), (scene.id, voices)
        assert len(voices) == len(set(voices)), (scene.id, voices)
        for role in scene.roles:
            assert role.name.strip() and role.name_en.strip(), (scene.id, role.role_id)
            assert role.persona.strip() and role.persona_cn.strip(), (scene.id, role.role_id)
            assert _ascii_letter_ratio(role.persona) >= 0.6, (scene.id, role.role_id)

        assert len(scene.opening_lines) >= 2, scene.id
        for line in scene.opening_lines:
            assert scene.role_of(line.role_id) is not None, (scene.id, line.role_id)
            assert line.text.strip() and line.text_cn.strip(), (scene.id, line.text)
            # 学员要开口/要听的英文句必须是英文 (0.6 留出标点/连字符的余地, 中文是 0.0)。
            assert _ascii_letter_ratio(line.text) >= 0.6, (scene.id, line.text)

        assert len(scene.suggestion_lines) >= 2, scene.id
        for line in scene.suggestion_lines:
            assert line.text.strip() and line.text_cn.strip(), (scene.id, line.text)
            assert _ascii_letter_ratio(line.text) >= 0.6, (scene.id, line.text)

        assert 3 <= len(scene.beats) <= 6, scene.id
        for beat in scene.beats:
            assert beat.strip(), (scene.id, beat)


def test_derived_views_are_pure_projections_of_the_lines() -> None:
    """``openings``/``suggestions``/``opening``/``suggestion``/``persona`` 全是派生读法:
    素材只有一份真相 (``opening_lines``/``suggestion_lines``/``roles``), 派生器必须逐字一致。"""
    for scene in dialogue_scenes.list_scenes():
        assert len(scene.opening_lines) >= 2 and len(scene.suggestion_lines) >= 2, scene.id
        assert scene.openings == tuple(line.text for line in scene.opening_lines), scene.id
        assert scene.suggestions == tuple(line.text for line in scene.suggestion_lines), scene.id
        assert scene.opening == scene.openings[0], scene.id
        assert scene.suggestion == scene.suggestions[0], scene.id
        assert scene.persona == " / ".join(role.persona_cn for role in scene.roles), scene.id
        assert scene.first_role is scene.roles[0], scene.id


def test_scene_messages_consumes_persona_beats_and_material() -> None:
    """扩容素材必须**有消费者** (否则素材只是一堆进不了 prompt 的死数据, §A5 的初衷)."""
    from app.api.v1 import dialogue

    scene = dialogue_scenes.resolve_scene("team_meeting")
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

    scene = dialogue_scenes.resolve_scene("team_meeting")
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
        "/api/v1/dialogue/generate", json={"scene": "coffee_shop", "device_id": DEV}
    )
    assert res.status_code == 200, res.text
    rows = (await db.execute(select(User).where(User.device_id == DEV))).scalars().all()
    assert [row.device_id for row in rows] == [DEV]


@pytest.mark.asyncio
async def test_generate_without_identity_writes_no_user(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    """不带身份 = 旧客户端的纯无状态行为: 零建行 (注册口径只对显式给身份的请求生效)。"""
    res = await client.post("/api/v1/dialogue/generate", json={"scene": "coffee_shop"})
    assert res.status_code == 200, res.text
    assert (await db.execute(select(User))).scalars().all() == []

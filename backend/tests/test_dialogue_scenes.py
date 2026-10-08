"""Tests for the /api/v1/dialogue/scenes endpoint + dialogue_scenes module."""

from __future__ import annotations

import httpx
import pytest

from app.services import dialogue_scenes


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
    for field in ("id", "title", "description", "kind"):
        assert field in scene, f"missing {field}"
    assert scene["kind"] == "catalog"


def test_catalog_scenes_carry_full_prompt_material_b6() -> None:
    """§3 B6 九场景扩容: 素材字段全员到位 (dataclass 已删默认值, 漏填直接构造 TypeError).

    钉的是**下限与锚点**而不是内容本身: beats 3-6 条、开场候补 ≥2 (含旧 ``opening``,
    选择器播的那句永远可以再多一句)、示范素材 ≥2 (含旧 ``suggestion``)、英文展示对非空。
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
        assert scene.persona.strip() and scene.user_role.strip(), scene.id
        assert 3 <= len(scene.beats) <= 6, scene.id
        assert len(scene.openings) >= 2, scene.id
        assert scene.opening in scene.openings
        assert len(scene.suggestions) >= 2, scene.id
        assert scene.suggestion in scene.suggestions


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

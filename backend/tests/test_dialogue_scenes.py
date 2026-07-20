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
async def test_dialogue_scenes_payload_shape(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/dialogue/scenes")
    scene = r.json()["scenes"][0]
    for field in ("id", "title", "description"):
        assert field in scene, f"missing {field}"


@pytest.mark.asyncio
async def test_dialogue_scenes_ids_match_catalog(client: httpx.AsyncClient) -> None:
    listed_ids = {s["id"] for s in (await client.get("/api/v1/dialogue/scenes")).json()["scenes"]}
    catalog_ids = {s.id for s in dialogue_scenes.list_scenes()}
    assert listed_ids == catalog_ids


def test_list_scenes_returns_at_least_four() -> None:
    assert len(dialogue_scenes.list_scenes()) >= 4


def test_get_scene_known_returns_matching_scene() -> None:
    scene = dialogue_scenes.get_scene("ordering_coffee")
    assert scene.id == "ordering_coffee"
    assert scene.opening
    assert scene.suggestion
    assert scene.next_suggestion
    assert scene.fallback_reply


def test_get_scene_unknown_falls_back_to_first() -> None:
    fallback = dialogue_scenes.list_scenes()[0]
    resolved = dialogue_scenes.get_scene("__nonexistent__")
    assert resolved.id == fallback.id


def test_scene_catalog_only_contains_unique_ids() -> None:
    ids = [s.id for s in dialogue_scenes.list_scenes()]
    assert len(ids) == len(set(ids))

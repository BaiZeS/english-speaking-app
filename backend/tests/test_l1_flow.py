from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_full_l1_read_along_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # 1. list lessons
        r = await c.get("/api/v1/lessons", params={"book": "nce1"})
        assert r.status_code == 200
        lessons = r.json()
        assert len(lessons) >= 1
        lesson_id = lessons[0]["id"]

        # 2. get roles for that lesson
        r = await c.get(f"/api/v1/lessons/{lesson_id}/roles")
        assert r.status_code == 200
        detail = r.json()
        first_line = detail["roles"][0]["lines"][0]
        ref_text = first_line["text"]
        line_id = first_line["id"]

        # 3. fetch TTS
        r = await c.get("/api/v1/tts", params={"text": ref_text, "voice": "k12_female"})
        assert r.status_code == 200
        assert r.json()["audio_url"]

        # 4. submit score
        fake_audio = base64.b64decode("AAAAGGZ0eXBpc29tAAAAAGlzbzZtcDQy")
        r = await c.post(
            "/api/v1/score",
            json={
                "lesson_id": lesson_id,
                "line_id": line_id,
                "ref_text": ref_text,
                "mode": "k12",
                "audio": base64.b64encode(fake_audio).decode("ascii"),
            },
        )
        assert r.status_code == 200, r.text
        score = r.json()
        assert 0 <= score["total"] <= 100
        assert score["word_details"], "should have word-level details"

        # 5. write history
        r = await c.post(
            "/api/v1/history",
            json={
                "device_id": "integration-test-device",
                "lesson_id": lesson_id,
                "line_id": line_id,
                "audio_path": "/tmp/x.m4a",
                "score_total": score["total"],
                "score_pronunciation": score["pronunciation"],
                "score_fluency": score["fluency"],
                "score_completeness": score["completeness"],
            },
        )
        assert r.status_code == 201

        # 6. read it back
        r = await c.get("/api/v1/history", params={"device_id": "integration-test-device"})
        assert r.status_code == 200
        assert len(r.json()) >= 1

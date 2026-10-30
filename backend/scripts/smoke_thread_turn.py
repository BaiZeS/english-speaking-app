"""真火端到端冒烟: 中文语音 -> 英文台词 + 语音条 -> 每轮评分回填 (v3.0 主链路).

跑法 (需要 backend/.env 里的真凭据; 缺凭据时讯飞会 401、TTS 会静默退 stub 假音频):

    cd backend && ./.venv/bin/python scripts/smoke_thread_turn.py

为什么值得单独留一个脚本: 这条链上每一段都各有替身测试, 但**替身测不出跨段的真实形状** ——
中文语音能不能真的被 `zh_cn` 听写出来、听写出来的中文能不能让 LLM 用英文把对话接下去、
台词能不能真的合成出可播的 48kHz 音频、评分作业能不能真的把那颗 pending 气泡翻成 ready。
这四段串起来才是学员手上的那一个动作。

它用**文件型 sqlite** 临时库, 不碰生产库 (`english_prod_5173`), 也不起服务端口。
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 临时库: 必须在 import app.config 之前定好, settings 是模块级单例。
_DB = Path(tempfile.gettempdir()) / f"smoke_thread_{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB}"
os.environ["ENV"] = "development"

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import thread_grading  # noqa: E402
from app.services.mimo_tts import MimoTtsProvider  # noqa: E402
from app.services.users import lookup_user  # noqa: E402

DEVICE = "smoke-device"
SCENE = "restaurant"
#: 学员这一句: 中文。真实用户说的就是这种带具体要求的短句。
LEARNER_CHINESE = "我想要一份牛肉面，汤里不要放香菜。"


async def chinese_pcm(text: str) -> bytes:
    """合成一句中文 -> 讯飞 IAT 要的 16k 单声道 PCM (TTS 落盘是 48k, 整数比抽取)."""
    result = await MimoTtsProvider().synthesize(text, "Mia")
    with wave.open(io.BytesIO(result.audio_bytes), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        pcm = w.readframes(n)
    if ch == 2:
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 4))
    if sr == 48000:
        pcm = b"".join(pcm[i : i + 2] for i in range(0, len(pcm), 6))
    return pcm


def show(kind: str, message: dict) -> None:
    role = message.get("role_id") or "我"
    audio = message.get("audio_url")
    flag = f"音频={audio}" if audio else ("音频=待补(audio_pending)" if message.get("audio_pending") else "无音频")
    print(f"  [{kind:<4}] {role:<3} {message.get('text', '')[:70]!r}  {flag}")
    if message.get("text_cn"):
        print(f"         中文: {message['text_cn'][:60]}")
    if message.get("grade"):
        g = message["grade"]
        print(f"         评分: status={g['status']} score={g['score']} axes={g['axes']}")
        if g.get("comment_cn"):
            print(f"         点评: {g['comment_cn'][:70]}")


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        print(f"场景目录: {len((await c.get('/api/v1/dialogue/scenes')).json()['scenes'])} 场")

        opened = await c.post(
            "/api/v1/dialogue/threads", json={"scene_key": SCENE}, params={"device_id": DEVICE}
        )
        assert opened.status_code == 201, opened.text
        thread = opened.json()
        print(f"\n开会话 {thread['id']}: 开场白 {len(thread['messages'])} 颗")
        for m in thread["messages"]:
            show(m["kind"], m)

        again = await c.post(
            "/api/v1/dialogue/threads", json={"scene_key": SCENE}, params={"device_id": DEVICE}
        )
        assert again.json()["id"] == thread["id"], "开线程不幂等"
        assert len(again.json()["messages"]) == len(thread["messages"]), "开场白被重复落了"
        print("  ✓ 二次开线程幂等 (同 id、不重复落开场白)")

        pcm = await chinese_pcm(LEARNER_CHINESE)
        print(f"\n学员中文语音 ({len(pcm) / 32000:.1f}s) -> 提交一轮")
        turn = await c.post(
            f"/api/v1/dialogue/threads/{thread['id']}/turn",
            json={"mode": "voice", "audio_b64": base64.b64encode(pcm).decode()},
            params={"device_id": DEVICE},
        )
        print(f"  HTTP {turn.status_code}")
        assert turn.status_code == 200, turn.text
        body = turn.json()
        for m in body["messages"]:
            show(m["kind"], m)

        user = next(m for m in body["messages"] if m["kind"] == "user")
        print(f"\n  听写结果: {user['recognized_text']!r}")
        print(f"  判出的语言: {user['spoke']}  (含汉字 => zh, 这一轮不该有发音轴)")
        grade = next(m for m in body["messages"] if m["kind"] == "grade")
        assert "pronunciation" not in grade["grade"]["axes"], "说中文却出了发音分"
        print("  ✓ 说中文这一轮没有发音轴")

        # 评分作业: 请求内只落 pending, 这里当场驱动作业把那颗气泡翻成 ready。
        uid = await _uid()
        await thread_grading.run_thread_grading_job(thread["id"], uid)
        after = await c.get(f"/api/v1/dialogue/threads/{thread['id']}", params={"device_id": DEVICE})
        final = after.json()
        print(f"\n判分回填后: grading_status={final['grading_status']}")
        g = [m for m in final["messages"] if m["kind"] == "grade"][-1]["grade"]
        print(f"  score={g['score']} axes={g['axes']}")
        print(f"  点评(中): {g['comment_cn']!r}")
        print(f"  点评(英): {g['comment']!r}")

    await engine.dispose()
    _DB.unlink(missing_ok=True)


async def _uid() -> str:
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as db:
        user = await lookup_user(db, device_id=DEVICE)
        assert user is not None
        return user.id


asyncio.run(main())

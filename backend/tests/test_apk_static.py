"""/static/apk 自托管 OTA 挂载的最小可用性.

真实挂载在 app import 期绑定 settings.apk_dir (backend/static/apk, gitignored),
不依赖 lifespan (ASGITransport 不跑 startup), 目录由 main 模块级 makedirs 保证。
probe 文件用唯一名 + finally 清理, 不污染同目录的正式 APK。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from httpx import AsyncClient

from app.config import settings


async def test_static_apk_serves_hosted_file(client: AsyncClient) -> None:
    name = f"_probe-{uuid.uuid4().hex}.apk"
    target = Path(settings.apk_dir) / name
    target.write_bytes(b"PK\x03\x04probe")
    try:
        r = await client.get(f"/static/apk/{name}")
        assert r.status_code == 200
        assert r.content == b"PK\x03\x04probe"
    finally:
        target.unlink(missing_ok=True)


async def test_static_apk_missing_file_is_404(client: AsyncClient) -> None:
    r = await client.get(f"/static/apk/_does-not-exist-{uuid.uuid4().hex}.apk")
    assert r.status_code == 404

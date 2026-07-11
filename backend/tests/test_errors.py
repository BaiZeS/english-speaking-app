"""应用错误类型与全局异常处理测试。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError, install_error_handler


@pytest.mark.asyncio
async def test_app_error_returns_json_status_and_message() -> None:
    app = FastAPI()
    install_error_handler(app)

    @app.get("/boom")
    async def boom() -> None:
        raise AppError(status_code=418, message="tea pot", code="TEAPOT")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "TEAPOT", "message": "tea pot"}}

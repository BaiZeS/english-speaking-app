"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1 import dialogue, health, history, lessons, score, tts
from app.config import settings
from app.core.errors import install_error_handler
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("INFO")
    logger.info("Starting English Assistant API | env={}", settings.env)
    # 确保 TTS 音频目录存在 (StaticFiles 挂载前目录必须存在)
    os.makedirs(settings.tts_audio_dir, exist_ok=True)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="English Speaking Assistant API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url="/redoc" if settings.env != "production" else None,
)

install_error_handler(app)
app.include_router(dialogue.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(history.router, prefix="/api/v1")
app.include_router(lessons.router, prefix="/api/v1")
app.include_router(tts.router, prefix="/api/v1")
app.include_router(score.router, prefix="/api/v1")

# 挂载 /static/tts 提供下载 TTS 合成音频 (URL 前缀与 audio_url 一致, 避免路径拼接错位)
app.mount(
    "/static/tts", StaticFiles(directory=settings.tts_audio_dir, check_dir=False), name="tts-static"
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "english-assistant", "version": "0.1.0"}

"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1 import (
    dialogue,
    dialogue_threads,
    health,
    llm,
    scene_specs,
    scenes,
    translate,
    tts,
    version,
)
from app.config import settings
from app.core.errors import install_error_handler
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("INFO")
    logger.info("Starting English Assistant API | env={}", settings.env)
    # 确保 TTS 音频目录存在 (StaticFiles 挂载前目录必须存在)
    os.makedirs(settings.tts_audio_dir, exist_ok=True)
    # 自托管 OTA 的 APK 发布目录 (见 config.apk_dir 注释与 scripts/publish_apk.sh)
    os.makedirs(settings.apk_dir, exist_ok=True)
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

# v3.0 之后后端只剩"情景对话"这一条产品线: 场景目录 + 自定义场景 + 会话线程 +
# 语音条 + 长按翻译。单词/课程/打基础/跟读/测评/统计/画像那批端点连同其服务层已整体
# 退役 (方案 S2.1/S2.8); **数据库表一律保留**, 只删代码路径。
app.include_router(dialogue.router, prefix="/api/v1")
app.include_router(dialogue_threads.router, prefix="/api/v1")
app.include_router(scene_specs.router, prefix="/api/v1")
# 自定义场景骨架与整课生成共用这一条轮询路由 (``GET /scenes/jobs/{job_id}``) ——
# 大扫除时只删 scenes.py 的 generate/detail/script/delete 与课程进度, 别把这里整删。
app.include_router(scenes.router, prefix="/api/v1")
app.include_router(tts.router, prefix="/api/v1")
app.include_router(translate.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(version.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1", tags=["health"])

# 挂载 /static/tts 提供下载 TTS 合成音频 (URL 前缀与 audio_url 一致, 避免路径拼接错位)
app.mount(
    "/static/tts", StaticFiles(directory=settings.tts_audio_dir, check_dir=False), name="tts-static"
)
# 自托管 OTA APK: 手机经 GitHub release 下载实测 ~10-40KB/s 不可用,
# /app/version 配 APP_APK_URL 指到 /static/apk/... 后由本挂载全速直出。
# 目录在 import 期即创建 (非仅 lifespan): ASGITransport 类测试不跑 lifespan,
# StaticFiles 在目录缺失时 lookup 直接 500 而非 404。
os.makedirs(settings.apk_dir, exist_ok=True)
app.mount(
    "/static/apk", StaticFiles(directory=settings.apk_dir, check_dir=False), name="apk-static"
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "english-assistant", "version": "0.1.0"}

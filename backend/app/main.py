"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1 import (
    ability,
    assessment,
    books,
    course_sessions,
    dialogue,
    expressions,
    health,
    history,
    lessons,
    llm,
    polish,
    scenes,
    score,
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
app.include_router(books.router, prefix="/api/v1")
app.include_router(dialogue.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(version.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(history.router, prefix="/api/v1")
app.include_router(lessons.router, prefix="/api/v1")
app.include_router(tts.router, prefix="/api/v1")
app.include_router(score.router, prefix="/api/v1")
# 情景课 (任务通关闭环) 画廊/详情/剧本 —— 计划 §5.3, 纯新增只读端点
app.include_router(scenes.router, prefix="/api/v1")
# 通关会话状态机 + 打基础 drill 评分 —— 计划 §5.3/§5.4, P2
# (P3/T4 在同一 router 补了 /mission、/hint、/finish-mission)
app.include_router(course_sessions.router, prefix="/api/v1")
# 能力画像 (EWMA 快照 + 雷达 + 轨迹) —— 计划 §5.6, P3
app.include_router(ability.router, prefix="/api/v1")
# 语法润色 / 个人表达库 —— 计划 §5.7, P3
app.include_router(polish.router, prefix="/api/v1")
app.include_router(expressions.router, prefix="/api/v1")
# CEFR 摸底测评 (题库/start/answer/complete) —— 计划 §5.3/§5.5-3, P4
app.include_router(assessment.router, prefix="/api/v1")

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

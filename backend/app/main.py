"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from app.api.v1 import health
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting English Assistant API | env={}", settings.env)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="English Speaking Assistant API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.env != "production" else None,
    redoc_url="/redoc" if settings.env != "production" else None,
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "english-assistant", "version": "0.1.0"}

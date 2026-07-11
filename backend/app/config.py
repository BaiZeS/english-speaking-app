"""应用配置。"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ====== 应用 ======
    env: str = Field(default="development")
    debug: bool = Field(default=True)
    api_v1_prefix: str = "/api/v1"

    # ====== 数据库 ======
    database_url: str = Field(
        default="postgresql+asyncpg://english:english@localhost:5432/english_dev"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ====== 讯飞 (主) ======
    xunfei_app_id: str = Field(default="")
    xunfei_api_key: str = Field(default="")
    xunfei_api_secret: str = Field(default="")

    # ====== OpenAI / 阿里 (备选) ======
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    aliyun_dashscope_key: str = Field(default="")

    # ====== TTS 缓存 ======
    tts_cache_ttl: int = Field(default=86400)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

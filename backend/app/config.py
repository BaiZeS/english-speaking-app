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

    # ====== 讯飞 ISE (语音评测, 保留) ======
    xunfei_app_id: str = Field(default="")
    xunfei_api_key: str = Field(default="")
    xunfei_api_secret: str = Field(default="")

    # ====== MiMo TTS ======
    mimo_api_key: str = Field(default="")
    mimo_tts_base_url: str = Field(default="https://api.xiaomimimo.com/v1")
    mimo_tts_model: str = Field(default="mimo-v2.5-tts")
    mimo_tts_default_voice: str = Field(default="Mia")
    mimo_tts_voices: str = Field(default="Mia,Chloe,Milo,Dean")
    # 合成音频文件的存放目录, 挂载到 /static
    tts_audio_dir: str = Field(default="static/tts")

    # ====== OpenAI / 阿里 (备选) ======
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    aliyun_dashscope_key: str = Field(default="")

    # ====== LLM (自由对话) ======
    # OpenAI 兼容端点 (阿里云百炼 Maas / OpenAI / 其它第三方代理都行).
    # 留空时 ``/dialogue/*`` 自动回退到内置 deterministic fallback.
    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    # 服务端默认模型 (判分/生成/实战对话恒用它). **默认留空**: 未配置的环境里
    # 解析链走 "首个 LLM_ALLOWED_MODELS -> 内置目录第一项" 的确定性回退
    # (见 ``llm_provider.resolve_server_default_model``), 不再藏一个可能已配额
    # 耗尽的具体模型 id (2026-08-31 实测 qwen-plus 系全 403; 本机 .env 配 qwen3.8-max).
    llm_default_model: str = Field(default="")
    # 逗号分隔的模型白名单, 限制客户端可选范围 **并** 作为服务端默认的回退第一项;
    # 留空则用代码内置的百炼目录.
    llm_allowed_models: str = Field(default="")
    # JSON 数组, 给企业自建代理场景追加自定义模型:
    #   '[{"id":"my-gpt","display_name":"My GPT","provider":"custom","description":"内网代理"}]'
    llm_extra_models_json: str = Field(default="")

    # ====== App 版本 (自动更新) ======
    # 客户端启动时拉取 ``GET /api/v1/app/version`` 比较, 大于当前版本就弹更新.
    app_latest_version: str = Field(default="1.0.0")
    app_apk_url: str = Field(default="")
    app_release_notes: str = Field(default="")
    # 是否强制升级 (``min_supported_version`` 大于此值的客户端必须升级才能进)
    app_min_supported_version: str = Field(default="")

    # ====== App 版本 (GitHub Releases 自动回源) ======
    # APP_GITHUB_REPO 设为 "owner/name" 后, GET /api/v1/app/version 会去
    # GitHub Releases API 拿 latest release 的 tag + APK asset URL. 走 TTL 缓存
    # (5 分钟) 避免触发 60 req/h 限流. 显式设置的 app_apk_url /
    # app_latest_version 始终覆盖 GitHub 回源, 方便自托管或灰度.
    app_github_repo: str = Field(default="")
    app_github_token: str = Field(default="")
    app_github_asset_name: str = Field(default="app-debug.apk")
    # 当一个 release 带多个 .apk asset 时, 按这个 glob 优先匹配.
    app_github_asset_glob: str = Field(default="EnglishAssistant-*.apk")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

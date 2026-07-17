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

    # ====== 讯飞 TTS ======
    # 默认 vcn 走超拟人 Spark TTS (美式英文女声). 切换到 v2 老音色 (xiaoyan 等)
    # 只需把 default 改回去并配 XUNFEI_API_KEY/SECRET, 不需改代码.
    xunfei_tts_default_vcn: str = Field(default="x5_EnUs_Grant_flow")
    # 逗号分隔的发音人列表, app 设置页可切换. 必须是 Spark TTS 控制台已开通的 vcn.
    xunfei_tts_voices: str = Field(default="x5_EnUs_Grant_flow,x5_EnUs_Lila_flow")
    # 合成音频文件的存放目录, 挂载到 /static
    tts_audio_dir: str = Field(default="static/tts")

    # ====== 讯飞 超拟人 TTS (主用) ======
    # Spark 超拟人合成 API (https://www.xfyun.cn/doc/spark/super%20smart-tts.html)
    # 鉴权用 APIPassword + x-api-key 请求头, 比 v2 的 hmac-sha256 URL 鉴权简单.
    # 端点固定, 控制台开通后即用. 未配置则自动 fallback 到 v2 老接口, 再降级到 stub.
    xunfei_spark_tts_password: str = Field(default="")
    xunfei_spark_tts_url: str = Field(
        default="wss://cbm01.cn-huabei-1.xf-yun.com/v1/private/mcd9m97e6"
    )

    # ====== OpenAI / 阿里 (备选) ======
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    aliyun_dashscope_key: str = Field(default="")

    # ====== LLM (自由对话) ======
    # OpenAI 兼容端点 (阿里云百炼 Maas / OpenAI / 其它第三方代理都行).
    # 留空时 ``/dialogue/*`` 自动回退到内置 deterministic fallback.
    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_default_model: str = Field(default="qwen-plus")
    # 逗号分隔的模型白名单, 限制客户端可选范围; 留空则用代码内置的百炼目录.
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

    # ====== TTS 缓存 ======
    tts_cache_ttl: int = Field(default=86400)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

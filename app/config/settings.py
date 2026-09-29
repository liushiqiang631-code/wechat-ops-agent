from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "微信公众号数据驱动运营 Agent"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_secret_key: SecretStr = Field(default=SecretStr("development-only"))
    business_timezone: str = "Asia/Shanghai"
    operator_name: str = "运营者"

    database_url: str = "sqlite:///./wechat_ops.db"
    object_storage_path: Path = Path("./outputs")
    workflow_checkpoint_path: Path = Path("./outputs/workflow_checkpoints.sqlite")

    text_model_provider: Literal["deepseek"] = "deepseek"
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_thinking_enabled: bool = True
    deepseek_reasoning_effort: Literal["low", "medium", "high"] = "high"
    # 单次请求的 completion 上限；思考 token 与正文 JSON 共用这个额度
    deepseek_max_output_tokens: int = Field(default=8_192, ge=256, le=65_536)

    wechat_account_name: str = ""
    wechat_app_id: str | None = None
    wechat_app_secret: SecretStr | None = None
    wechat_original_id: str | None = None
    wechat_api_base: str = "https://api.weixin.qq.com"
    wechat_draft_enabled: bool = False

    image_model_enabled: bool = False
    image_model_provider: Literal["siliconflow", "dashscope", "web", "disabled"] = "disabled"
    image_search_provider: Literal["wikimedia", "disabled"] = "wikimedia"
    siliconflow_api_base: str = "https://api.siliconflow.cn/v1"
    siliconflow_api_key: SecretStr | None = None
    # 线上文生图可用模型以 GET /models 为准；Z-Image-Turbo 约 ¥0.10/张，
    # Qwen/Qwen-Image 约 ¥0.25/张（擅长图内中文文字），Kwai-Kolors/Kolors 免费
    siliconflow_image_model: str = "Tongyi-MAI/Z-Image-Turbo"

    dashscope_api_base: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_api_key: SecretStr | None = None
    dashscope_image_model: str = "qwen-image-3.0-pro"
    dashscope_image_size: str = "1024*1024"
    # qwen-image-3.0-pro 在百炼的限流为 1 RPM，串行生成时在请求之间等待
    dashscope_inter_request_delay: float = 60.0

    web_search_provider: Literal["jina_bing", "disabled"] = "jina_bing"
    web_search_max_results: int = 8
    web_search_timeout: float = 30.0

    mcp_servers_path: Path = Path("./mcp_servers.json")

    max_research_queries: int = Field(default=8, ge=1, le=20)
    max_sources: int = Field(default=20, ge=1, le=50)
    max_review_rounds: int = Field(default=2, ge=0, le=2)
    max_total_tokens: int = Field(default=60_000, ge=1_000, le=1_000_000)
    metrics_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    cover_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    auto_publish: bool = False
    enable_intentional_typos: bool = False
    external_content_trust: Literal["untrusted"] = "untrusted"

    scheduler_enabled: bool = False

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.business_timezone)

    @property
    def ai_image_generation_available(self) -> bool:
        if not self.image_model_enabled:
            return False
        if self.image_model_provider == "siliconflow":
            return self.siliconflow_api_key is not None
        if self.image_model_provider == "dashscope":
            return self.dashscope_api_key is not None
        return False

    @property
    def web_image_search_available(self) -> bool:
        return self.image_search_provider == "wikimedia"

    @property
    def web_search_available(self) -> bool:
        return self.web_search_provider == "jina_bing"

    def public_dict(self) -> dict[str, Any]:
        excluded = {
            "app_secret_key",
            "deepseek_api_key",
            "wechat_app_secret",
            "siliconflow_api_key",
            "dashscope_api_key",
        }
        return self.model_dump(exclude=excluded)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()

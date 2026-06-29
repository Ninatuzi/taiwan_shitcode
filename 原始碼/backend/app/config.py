"""集中配置：所有外部依赖地址、模型名、并发数、清理周期、上传上限全部走环境变量。

对应指令书第 10 节「配置项清单」。生产/测试切换只改 .env，不改代码。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 数据库 ──
    # 优先使用完整 DSN；未提供时由分项拼装。
    pg_dsn: str | None = Field(default=None, alias="PG_DSN")
    pg_host: str = Field(default="127.0.0.1", alias="PG_HOST")
    pg_port: int = Field(default=5432, alias="PG_PORT")
    pg_user: str = Field(default="bms", alias="PG_USER")
    pg_password: str = Field(default="bms", alias="PG_PASSWORD")
    pg_db: str = Field(default="bms", alias="PG_DB")

    # ── Redis ──
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")

    # ── 文件存储 ──
    data_dir: str = Field(default="/data/cases", alias="DATA_DIR")
    file_retention_days: int = Field(default=7, alias="FILE_RETENTION_DAYS")
    max_upload_mb: int = Field(default=50, alias="MAX_UPLOAD_MB")
    cleanup_interval_hours: int = Field(default=24, alias="CLEANUP_INTERVAL_HOURS")

    # ── 队列与并发 ──
    max_running: int = Field(default=2, alias="MAX_RUNNING")
    max_queued: int = Field(default=2, alias="MAX_QUEUED")

    # ── 本地模型（OpenAI 兼容接口）──
    llm_base_url: str = Field(default="http://10.0.6.89:8080/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="DeepSeek_32B_f16", alias="LLM_MODEL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_max_input_tokens: int = Field(default=24000, alias="LLM_MAX_INPUT_TOKENS")
    llm_max_output_tokens: int = Field(default=16000, alias="LLM_MAX_OUTPUT_TOKENS")
    llm_timeout: int = Field(default=600, alias="LLM_TIMEOUT")

    # ── 嵌入模型 ──
    embed_base_url: str = Field(default="http://10.7.5.237:5001/v1", alias="EMBED_BASE_URL")
    embed_model: str = Field(default="bge-m3", alias="EMBED_MODEL")
    embed_dim: int = Field(default=1024, alias="EMBED_DIM")

    # ── 覆盖引擎 ──
    combination_strength: str = Field(default="pairwise", alias="COMBINATION_STRENGTH")
    bva_tolerance_voltage_static_mv: float = Field(default=10.0, alias="BVA_TOLERANCE_VOLTAGE_STATIC_MV")
    bva_tolerance_voltage_dynamic_mv: float = Field(default=30.0, alias="BVA_TOLERANCE_VOLTAGE_DYNAMIC_MV")
    bva_tolerance_current_ma: float = Field(default=10.0, alias="BVA_TOLERANCE_CURRENT_MA")
    bva_tolerance_temperature_c: float = Field(default=1.0, alias="BVA_TOLERANCE_TEMPERATURE_C")

    @property
    def sqlalchemy_dsn(self) -> str:
        """SQLAlchemy 用的连接串（psycopg3 driver）。"""
        if self.pg_dsn:
            # 允许用户给标准 libpq DSN；统一加上 driver 前缀。
            if self.pg_dsn.startswith("postgresql+"):
                return self.pg_dsn
            if self.pg_dsn.startswith("postgresql://"):
                return self.pg_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
            return self.pg_dsn
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

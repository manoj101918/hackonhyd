"""Application settings, loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RUNTIME_DIR = DATA_DIR / "runtime"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    hindsight_base_url: str = "https://api.hindsight.vectorize.io"
    hindsight_api_key: str = ""
    hindsight_bank_id: str = "acme-incidents"
    hindsight_timeout_s: float = 30.0
    recall_timeout_s: float = 20.0
    reflect_timeout_s: float = 60.0
    retain_timeout_s: float = 90.0

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "qwen/qwen3.8-27b"
    llm_timeout_s: float = 45.0

    agent_max_steps: int = 8
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

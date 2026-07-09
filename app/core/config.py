"""pydantic-settings 기반 전역 설정 관리."""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = True

    upstage_api_key: str = ""
    llm_model: str = "solar-pro3"

    supabase_url: str = ""
    supabase_key: str = ""

    database_url: str = ""

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()


settings = get_settings()

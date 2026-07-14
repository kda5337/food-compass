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

    # [2026-07-14] LLMOps 트레이싱(선택 가점) — langfuse 패키지는 pyproject.toml의
    # "stretch"(선택) 그룹에 있어 CI/팀원 환경엔 기본 설치가 안 됨. 값이 비어있으면
    # app/core/tracing.py가 트레이싱 없이 조용히 넘어감(§0-1 CI 검증에 영향 없음).
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

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

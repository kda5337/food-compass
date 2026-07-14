"""pydantic-settings 기반 전역 설정 관리."""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = True

    upstage_api_key: str = ""
    llm_model: str = "solar-pro3"
    # [2026-07-15] 주 모델(llm_model) 호출이 실패할 때 대비하는 백업 모델.
    # LiteLLM 같은 게이트웨이 없이 app/core/llm.py에서 코드로 직접 폴백 처리.
    # 값이 비어있으면 폴백 없이 주 모델만 사용(기존 동작과 동일).
    llm_fallback_model: str = "solar-pro"

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

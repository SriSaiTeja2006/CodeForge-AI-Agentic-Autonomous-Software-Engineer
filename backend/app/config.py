from pathlib import Path
from functools import lru_cache
from typing import List
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from backend/.env and environment variables."""

    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/codeforge_ai"
    GROQ_API_KEY: SecretStr = SecretStr("")
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GITHUB_TOKEN: SecretStr = SecretStr("")
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    ENABLE_IN_PROCESS_WORKER: bool = False
    WORKER_POLL_INTERVAL: float = 1.0
    WORKER_STALE_TIMEOUT: int = 300
    TASK_TIMEOUT: int = 300
    REQUIRE_HUMAN_APPROVAL: bool = False
    ALLOW_HOST_TEST_RUNNER: bool = False
    ALLOW_DRAFT_PR_ON_VERIFICATION_FAILURE: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        """Return CORS_ORIGINS as a cleaned list of origin strings."""
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def sync_database_url(self) -> str:
        """Ensure psycopg2 dialect is specified for standard PostgreSQL URLs."""
        url = self.DATABASE_URL.strip()
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()

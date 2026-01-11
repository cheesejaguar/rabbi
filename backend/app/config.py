"""Application configuration."""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "rebbe.dev"
    app_version: str = "1.0.0"
    debug: bool = False

    # OpenRouter configuration
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-sonnet-4-20250514"

    # WorkOS SSO configuration
    workos_api_key: str = ""
    workos_client_id: str = ""
    session_secret_key: str = "change-me-in-production"
    workos_redirect_uri: str = "http://localhost:8613/auth/callback"

    # Database configuration (Vercel Postgres / Neon)
    database_url: str = ""
    postgres_url: str = ""  # Vercel uses this env var name

    cors_origins: list[str] = ["*"]

    @property
    def db_url(self) -> str:
        """Get database URL, preferring POSTGRES_URL (Vercel) over DATABASE_URL."""
        return self.postgres_url or self.database_url

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

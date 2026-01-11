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
    # Full connection URLs
    database_url: str = ""
    postgres_url: str = ""  # Vercel uses this env var name

    # Individual connection parameters (Vercel Postgres provides these)
    pghost: str = ""
    pguser: str = ""
    pgdatabase: str = ""
    pgpassword: str = ""
    postgres_host: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_database: str = ""

    cors_origins: list[str] = ["*"]

    @property
    def db_url(self) -> str:
        """Get database URL for connection.

        Priority (per Neon/Vercel docs):
        1. DATABASE_URL - pooled connection, recommended for serverless
        2. POSTGRES_URL - legacy Vercel Postgres variable
        3. Constructed from individual PG*/POSTGRES_* parameters
        """
        # Prefer DATABASE_URL (pooled connection for serverless)
        if self.database_url:
            return self.database_url
        if self.postgres_url:
            return self.postgres_url

        # Construct from individual parameters (prefer PG* over POSTGRES_*)
        host = self.pghost or self.postgres_host
        user = self.pguser or self.postgres_user
        password = self.pgpassword or self.postgres_password
        database = self.pgdatabase or self.postgres_database

        if host and user and password and database:
            return f"postgresql://{user}:{password}@{host}/{database}?sslmode=require"

        return ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

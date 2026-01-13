"""Application configuration."""

import logging
from functools import lru_cache
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings
from pydantic import field_validator

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "rebbe.dev"
    app_version: str = "1.0.0"
    debug: bool = False

    # Environment: "development" or "production"
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment.lower() == "production"

    # Gateway selection: "vercel" (default) or "openrouter"
    gateway: str = "vercel"

    # Vercel AI Gateway configuration
    ai_gateway_api_key: str = ""
    ai_gateway_base_url: str = "https://ai-gateway.vercel.sh/v1"

    # OpenRouter configuration (alternative gateway)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # LLM Model (works with both gateways)
    llm_model: str = "anthropic/claude-sonnet-4-20250514"

    # ElevenLabs TTS configuration
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "hQkoM7ZD59w5rbeIqZY4"

    # Stripe payment configuration
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    @property
    def llm_api_key(self) -> str:
        """Get the API key for the selected gateway."""
        if self.gateway.lower() == "vercel":
            return self.ai_gateway_api_key
        return self.openrouter_api_key

    @property
    def llm_base_url(self) -> str:
        """Get the base URL for the selected gateway."""
        if self.gateway.lower() == "vercel":
            return self.ai_gateway_base_url
        return self.openrouter_base_url

    # WorkOS SSO configuration
    workos_api_key: str = ""
    workos_client_id: str = ""
    session_secret_key: str = "change-me-in-production"
    workos_redirect_uri: str = "http://localhost:8613/auth/callback"

    @field_validator('session_secret_key')
    @classmethod
    def validate_session_secret(cls, v, info):
        """Validate session secret is secure in production."""
        # Get environment from values if available
        env = info.data.get('environment', 'development') if info.data else 'development'
        if env.lower() == 'production':
            if v == "change-me-in-production":
                raise ValueError("SESSION_SECRET_KEY must be changed in production")
            if len(v) < 32:
                raise ValueError("SESSION_SECRET_KEY must be at least 32 characters in production")
        return v

    # Database configuration (Vercel Postgres / Neon)
    # Full connection URLs
    database_url: str = ""
    database_url_unpooled: str = ""
    postgres_url: str = ""  # Vercel uses this env var name
    postgres_url_non_pooling: str = ""
    postgres_url_no_ssl: str = ""
    postgres_prisma_url: str = ""

    # Individual connection parameters (Vercel Postgres provides these)
    pghost: str = ""
    pghost_unpooled: str = ""
    pguser: str = ""
    pgdatabase: str = ""
    pgpassword: str = ""
    postgres_host: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_database: str = ""

    # Neon Auth environment variables (not used but must be accepted)
    next_public_stack_project_id: str = ""
    next_public_stack_publishable_client_key: str = ""
    stack_secret_server_key: str = ""

    # CORS origins - set via environment variable for production
    # Default allows localhost for development
    cors_origins: list[str] = [
        "http://localhost:8613",
        "http://127.0.0.1:8613",
    ]

    # Rate limiting settings
    rate_limit_per_minute: int = 30  # Requests per minute per IP
    rate_limit_chat_per_minute: int = 10  # Chat requests per minute per user

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
            # URL-encode user and password to handle special characters
            encoded_user = quote_plus(user)
            encoded_password = quote_plus(password)
            return f"postgresql://{encoded_user}:{encoded_password}@{host}/{database}?sslmode=require"

        return ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

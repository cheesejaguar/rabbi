"""Application configuration via pydantic-settings.

Loads all settings from environment variables (and an optional ``.env``
file in development). Supports dual AI gateway backends:

- **Vercel AI Gateway** (default) -- routes LLM calls through Vercel's
  managed proxy with built-in cost tracking and failover.
- **OpenRouter** -- alternative multi-provider gateway for local dev
  or when Vercel AI Gateway is unavailable.

The ``GATEWAY`` env var selects between them; computed properties
``llm_api_key`` and ``llm_base_url`` return the correct values.

The module exposes a single ``get_settings()`` function decorated with
``@lru_cache`` so that only one ``Settings`` instance is ever created
per process (singleton pattern).
"""

import logging
from functools import lru_cache
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings
from pydantic import field_validator

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Fields are grouped by domain. Computed ``@property`` attributes
    derive runtime values from the raw settings (e.g., selecting the
    correct API key based on the chosen gateway).
    """

    # -------------------------------------------------------------------
    # App Metadata
    # -------------------------------------------------------------------
    app_name: str = "rebbe.dev"
    app_version: str = "1.0.0"
    debug: bool = False

    # Environment: "development" or "production"
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in production (case-insensitive)."""
        return self.environment.lower() == "production"

    # -------------------------------------------------------------------
    # AI Gateway Selection
    # -------------------------------------------------------------------
    # Set GATEWAY=vercel (default) or GATEWAY=openrouter to choose which
    # LLM backend is used. The computed properties below resolve the
    # appropriate API key and base URL.
    gateway: str = "vercel"

    # Vercel AI Gateway configuration
    ai_gateway_api_key: str = ""
    ai_gateway_base_url: str = "https://ai-gateway.vercel.sh/v1"

    # OpenRouter configuration (alternative gateway)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # -------------------------------------------------------------------
    # LLM Configuration
    # -------------------------------------------------------------------
    # Model identifier in "<provider>/<model>" format, compatible with
    # both Vercel AI Gateway and OpenRouter.
    llm_model: str = "anthropic/claude-sonnet-4-20250514"

    # -------------------------------------------------------------------
    # TTS Configuration (ElevenLabs)
    # -------------------------------------------------------------------
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "hQkoM7ZD59w5rbeIqZY4"  # Default voice

    # -------------------------------------------------------------------
    # Stripe Payments
    # -------------------------------------------------------------------
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    @property
    def llm_api_key(self) -> str:
        """Return the API key for the currently selected gateway.

        When ``gateway`` is ``"vercel"``, returns ``ai_gateway_api_key``;
        otherwise returns ``openrouter_api_key``.
        """
        if self.gateway.lower() == "vercel":
            return self.ai_gateway_api_key
        return self.openrouter_api_key

    @property
    def llm_base_url(self) -> str:
        """Return the base URL for the currently selected gateway.

        When ``gateway`` is ``"vercel"``, returns ``ai_gateway_base_url``;
        otherwise returns ``openrouter_base_url``.
        """
        if self.gateway.lower() == "vercel":
            return self.ai_gateway_base_url
        return self.openrouter_base_url

    # -------------------------------------------------------------------
    # WorkOS Authentication
    # -------------------------------------------------------------------
    workos_api_key: str = ""
    workos_client_id: str = ""
    session_secret_key: str = "change-me-in-production"
    workos_redirect_uri: str = "http://localhost:8613/auth/callback"

    # Vercel deployment URL (automatically set by Vercel for preview deployments)
    vercel_url: str = ""

    @property
    def effective_redirect_uri(self) -> str:
        """Compute the WorkOS OAuth redirect URI for the current environment.

        For non-production environments where ``VERCEL_URL`` is set (i.e.,
        Vercel preview deployments), the redirect URI is constructed from
        the deployment URL. Otherwise falls back to the explicitly
        configured ``workos_redirect_uri``.

        Returns:
            The full callback URL (e.g., ``https://<deploy>.vercel.app/auth/callback``).
        """
        if not self.is_production and self.vercel_url:
            # VERCEL_URL doesn't include protocol, add https://
            return f"https://{self.vercel_url}/auth/callback"
        return self.workos_redirect_uri

    @field_validator('session_secret_key')
    @classmethod
    def validate_session_secret(cls, v, info):
        """Ensure the session secret meets minimum security requirements in production.

        In production, the default placeholder value is rejected and the
        key must be at least 32 characters long.

        Args:
            v: The session secret key value.
            info: Pydantic validation context containing other field values.

        Returns:
            The validated session secret key.

        Raises:
            ValueError: If the key is insecure for a production deployment.
        """
        # Get environment from values if available
        env = info.data.get('environment', 'development') if info.data else 'development'
        if env.lower() == 'production':
            if v == "change-me-in-production":
                raise ValueError("SESSION_SECRET_KEY must be changed in production")
            if len(v) < 32:
                raise ValueError("SESSION_SECRET_KEY must be at least 32 characters in production")
        return v

    # -------------------------------------------------------------------
    # Database (Vercel Postgres / Neon)
    # -------------------------------------------------------------------
    # Full connection URLs -- Vercel and Neon provide multiple URL formats.
    database_url: str = ""           # Pooled connection (recommended for serverless)
    database_url_unpooled: str = ""  # Direct connection (for migrations)
    postgres_url: str = ""           # Legacy Vercel Postgres env var name
    postgres_url_non_pooling: str = ""
    postgres_url_no_ssl: str = ""
    postgres_prisma_url: str = ""

    # Individual connection parameters (Vercel Postgres provides these as
    # separate env vars; used as fallback when no full URL is available).
    pghost: str = ""
    pghost_unpooled: str = ""
    pguser: str = ""
    pgdatabase: str = ""
    pgpassword: str = ""
    postgres_host: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_database: str = ""

    # Neon Auth environment variables (accepted but unused by this app)
    next_public_stack_project_id: str = ""
    next_public_stack_publishable_client_key: str = ""
    stack_secret_server_key: str = ""

    # CORS origins -- set via environment variable for production.
    # Default allows localhost for development.
    cors_origins: list[str] = [
        "http://localhost:8613",
        "http://127.0.0.1:8613",
    ]

    # -------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------
    rate_limit_per_minute: int = 30    # General API requests per minute per IP
    rate_limit_chat_per_minute: int = 10  # Chat requests per minute per user/IP

    # -------------------------------------------------------------------
    # Guest Security
    # -------------------------------------------------------------------
    guest_ip_chat_limit: int = 3       # Max chats per IP per day (guards against cookie clearing)
    guest_rate_limit_per_minute: int = 5  # Stricter rate limit for unauthenticated users
    ip_block_threshold: int = 10       # Violations before the IP is auto-blocked
    ip_block_duration: int = 3600      # Block duration in seconds (1 hour)
    max_message_length: int = 10000    # Maximum characters in a single chat message

    @property
    def db_url(self) -> str:
        """Resolve the database connection URL from available configuration.

        Resolution priority (per Neon/Vercel documentation):

        1. ``DATABASE_URL`` -- pooled connection, recommended for serverless.
        2. ``POSTGRES_URL`` -- legacy Vercel Postgres variable.
        3. Constructed from individual ``PG*`` / ``POSTGRES_*`` parameters,
           with ``quote_plus`` applied to user and password to safely handle
           special characters (e.g., ``@``, ``#``, ``%``) in credentials.

        Returns:
            A ``postgresql://`` connection string, or an empty string if
            no database is configured.
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
    """Return the singleton Settings instance (cached via ``@lru_cache``).

    Because ``@lru_cache`` memoizes the return value, the ``.env`` file
    is read and environment variables are parsed only once per process.

    Returns:
        The application ``Settings`` instance.
    """
    return Settings()

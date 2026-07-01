"""Tests for config.py."""

import pytest
import os
from unittest.mock import patch

from app.config import Settings, get_settings


class TestSettings:
    """Test Settings class."""

    def test_default_values(self):
        """Test default settings values."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.app_name == "rebbe.dev"
            assert settings.app_version == "1.0.0"
            assert settings.debug is False
            assert settings.gateway == "vercel"
            assert settings.ai_gateway_api_key == ""
            assert settings.ai_gateway_base_url == "https://ai-gateway.vercel.sh/v1"
            assert settings.openrouter_api_key == ""
            assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
            assert settings.llm_model == "anthropic/claude-sonnet-5"
            # Secure defaults for CORS - localhost only
            assert settings.cors_origins == ["http://localhost:8613", "http://127.0.0.1:8613"]
            # Rate limiting defaults
            assert settings.rate_limit_per_minute == 30
            assert settings.rate_limit_chat_per_minute == 10

    def test_env_override(self):
        """Test that environment variables override defaults."""
        env_vars = {
            "APP_NAME": "Test Rabbi",
            "APP_VERSION": "2.0.0",
            "DEBUG": "true",
            "OPENROUTER_API_KEY": "test-key-123",
            "OPENROUTER_BASE_URL": "https://custom.openrouter.ai/api/v1",
            "LLM_MODEL": "anthropic/claude-opus-4-20250514",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.app_name == "Test Rabbi"
            assert settings.app_version == "2.0.0"
            assert settings.debug is True
            assert settings.openrouter_api_key == "test-key-123"
            assert settings.openrouter_base_url == "https://custom.openrouter.ai/api/v1"
            assert settings.llm_model == "anthropic/claude-opus-4-20250514"

    def test_cors_origins_default(self):
        """Test default CORS origins are secure (localhost only)."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            # Should NOT allow all origins by default
            assert "*" not in settings.cors_origins
            # Should allow localhost for development
            assert "http://localhost:8613" in settings.cors_origins

    def test_cors_wildcard_rejected_in_production(self):
        """Test that a wildcard CORS origin fails validation in production."""
        env_vars = {
            "ENVIRONMENT": "production",
            "SESSION_SECRET_KEY": "a-very-secure-session-secret-key-for-testing-production",
            "CORS_ORIGINS": '["*"]',
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(Exception):
                Settings(_env_file=None)

    def test_cors_wildcard_allowed_outside_production(self):
        """Test that a wildcard CORS origin is still permitted in development."""
        env_vars = {
            "CORS_ORIGINS": '["*"]',
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.cors_origins == ["*"]

    def test_gateway_vercel_default(self):
        """Test that Vercel gateway is used by default."""
        env_vars = {
            "AI_GATEWAY_API_KEY": "vercel-key",
            "OPENROUTER_API_KEY": "openrouter-key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.gateway == "vercel"
            assert settings.llm_api_key == "vercel-key"
            assert settings.llm_base_url == "https://ai-gateway.vercel.sh/v1"

    def test_gateway_openrouter(self):
        """Test OpenRouter gateway selection."""
        env_vars = {
            "GATEWAY": "openrouter",
            "AI_GATEWAY_API_KEY": "vercel-key",
            "OPENROUTER_API_KEY": "openrouter-key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.gateway == "openrouter"
            assert settings.llm_api_key == "openrouter-key"
            assert settings.llm_base_url == "https://openrouter.ai/api/v1"

    def test_gateway_case_insensitive(self):
        """Test that gateway selection is case insensitive."""
        env_vars = {
            "GATEWAY": "VERCEL",
            "AI_GATEWAY_API_KEY": "vercel-key",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.llm_api_key == "vercel-key"

    def test_db_url_prefers_database_url(self):
        """Test that db_url prefers DATABASE_URL (pooled connection)."""
        env_vars = {
            "DATABASE_URL": "postgresql://pooled@host/db",
            "POSTGRES_URL": "postgresql://legacy@host/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.db_url == "postgresql://pooled@host/db"

    def test_db_url_falls_back_to_postgres_url(self):
        """Test that db_url falls back to POSTGRES_URL."""
        env_vars = {
            "POSTGRES_URL": "postgresql://legacy@host/db",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.db_url == "postgresql://legacy@host/db"

    def test_db_url_constructs_from_pg_params(self):
        """Test that db_url can be constructed from PG* parameters."""
        env_vars = {
            "PGHOST": "db.example.com",
            "PGUSER": "myuser",
            "PGPASSWORD": "mypass",
            "PGDATABASE": "mydb",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.db_url == "postgresql://myuser:mypass@db.example.com/mydb?sslmode=require"

    def test_db_url_constructs_from_postgres_params(self):
        """Test that db_url can be constructed from POSTGRES_* parameters."""
        env_vars = {
            "POSTGRES_HOST": "db.example.com",
            "POSTGRES_USER": "myuser",
            "POSTGRES_PASSWORD": "mypass",
            "POSTGRES_DATABASE": "mydb",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.db_url == "postgresql://myuser:mypass@db.example.com/mydb?sslmode=require"

    def test_db_url_pg_params_take_precedence(self):
        """Test that PG* params take precedence over POSTGRES_* params."""
        env_vars = {
            "PGHOST": "pg-host.com",
            "PGUSER": "pguser",
            "PGPASSWORD": "pgpass",
            "PGDATABASE": "pgdb",
            "POSTGRES_HOST": "postgres-host.com",
            "POSTGRES_USER": "postgresuser",
            "POSTGRES_PASSWORD": "postgrespass",
            "POSTGRES_DATABASE": "postgresdb",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert "pguser" in settings.db_url
            assert "pg-host.com" in settings.db_url

    def test_db_url_returns_empty_when_incomplete(self):
        """Test that db_url returns empty string when params incomplete."""
        env_vars = {
            "PGHOST": "db.example.com",
            "PGUSER": "myuser",
            # Missing PGPASSWORD and PGDATABASE
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.db_url == ""

    def test_db_url_returns_empty_when_not_configured(self):
        """Test that db_url returns empty string when nothing configured."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.db_url == ""

    def test_db_url_encodes_special_characters(self):
        """Test that special characters in password are URL-encoded."""
        env_vars = {
            "PGHOST": "db.example.com",
            "PGUSER": "user@domain",
            "PGPASSWORD": "p@ss:word/with?special=chars",
            "PGDATABASE": "mydb",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            # Special chars should be URL-encoded
            assert "p%40ss%3Aword%2Fwith%3Fspecial%3Dchars" in settings.db_url
            assert "user%40domain" in settings.db_url
            # The URL should still be valid PostgreSQL format
            assert settings.db_url.startswith("postgresql://")
            assert "@db.example.com/mydb?sslmode=require" in settings.db_url


class TestIsProduction:
    """Test is_production property."""

    def test_is_production_true(self):
        """Test is_production returns True for production environment."""
        env_vars = {
            "ENVIRONMENT": "production",
            "SESSION_SECRET_KEY": "a-very-secure-session-secret-key-for-testing-production",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.is_production is True

    def test_is_production_false_for_development(self):
        """Test is_production returns False for development environment."""
        env_vars = {"ENVIRONMENT": "development"}
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.is_production is False

    def test_is_production_case_insensitive(self):
        """Test is_production is case insensitive."""
        env_vars = {
            "ENVIRONMENT": "PRODUCTION",
            "SESSION_SECRET_KEY": "a-very-secure-session-secret-key-for-testing-production",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.is_production is True

    def test_is_production_default_false(self):
        """Test is_production defaults to False."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.is_production is False


class TestEffectiveRedirectUri:
    """Test effective_redirect_uri property."""

    def test_uses_workos_redirect_uri_in_production(self):
        """Test that production uses the configured workos_redirect_uri."""
        env_vars = {
            "ENVIRONMENT": "production",
            "SESSION_SECRET_KEY": "a-very-secure-session-secret-key-for-testing-production",
            "WORKOS_REDIRECT_URI": "https://rebbe.dev/auth/callback",
            "VERCEL_URL": "rebbe-preview-123.vercel.app",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.effective_redirect_uri == "https://rebbe.dev/auth/callback"

    def test_uses_vercel_url_in_preview(self):
        """Test that preview deployment falls back to VERCEL_URL when
        VERCEL_BRANCH_URL isn't set."""
        env_vars = {
            "ENVIRONMENT": "preview",
            "WORKOS_REDIRECT_URI": "https://rebbe.dev/auth/callback",
            "VERCEL_URL": "rebbe-preview-123.vercel.app",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.effective_redirect_uri == "https://rebbe-preview-123.vercel.app/auth/callback"

    def test_prefers_vercel_branch_url_over_vercel_url(self):
        """VERCEL_BRANCH_URL (the stable per-branch alias users actually
        click through PR preview links) must win over VERCEL_URL (the
        ephemeral per-deployment URL that changes on every push) -- using
        the wrong one causes the OAuth state cookie to be set on one domain
        while WorkOS redirects the callback to a different one."""
        env_vars = {
            "ENVIRONMENT": "preview",
            "WORKOS_REDIRECT_URI": "https://rebbe.dev/auth/callback",
            "VERCEL_URL": "rabbi-a1b2c3d4-cheesejaguar.vercel.app",
            "VERCEL_BRANCH_URL": "rabbi-git-my-branch-cheesejaguar.vercel.app",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.effective_redirect_uri == "https://rabbi-git-my-branch-cheesejaguar.vercel.app/auth/callback"

    def test_uses_vercel_url_in_development_with_vercel_url(self):
        """Test that development with VERCEL_URL uses dynamic redirect."""
        env_vars = {
            "ENVIRONMENT": "development",
            "WORKOS_REDIRECT_URI": "http://localhost:8613/auth/callback",
            "VERCEL_URL": "rebbe-dev-456.vercel.app",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.effective_redirect_uri == "https://rebbe-dev-456.vercel.app/auth/callback"

    def test_uses_workos_redirect_uri_without_vercel_url(self):
        """Test that without VERCEL_URL, workos_redirect_uri is used."""
        env_vars = {
            "ENVIRONMENT": "development",
            "WORKOS_REDIRECT_URI": "http://localhost:8613/auth/callback",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.effective_redirect_uri == "http://localhost:8613/auth/callback"

    def test_default_redirect_uri(self):
        """Test default redirect URI without any configuration."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.effective_redirect_uri == "http://localhost:8613/auth/callback"


class TestAdminEmails:
    """Test the platform-admin allowlist configuration."""

    def test_default_admin_is_cheesejaguar(self):
        """The default allowlist designates cheesejaguar@gmail.com as admin."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.admin_email_list == ["cheesejaguar@gmail.com"]
            assert settings.is_admin_email("cheesejaguar@gmail.com") is True

    def test_is_admin_email_is_case_insensitive(self):
        """Admin matching ignores case and surrounding whitespace."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.is_admin_email("  CheeseJaguar@Gmail.com ") is True
            assert settings.is_admin_email("someone-else@example.com") is False
            assert settings.is_admin_email(None) is False
            assert settings.is_admin_email("") is False

    def test_admin_emails_env_override_comma_separated(self):
        """ADMIN_EMAILS accepts a comma-separated, mixed-case list."""
        env_vars = {"ADMIN_EMAILS": "a@x.com, B@Y.com ,c@z.com"}
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)
            assert settings.admin_email_list == ["a@x.com", "b@y.com", "c@z.com"]
            assert settings.is_admin_email("b@y.com") is True
            # The default admin is replaced, not appended to.
            assert settings.is_admin_email("cheesejaguar@gmail.com") is False

    def test_admin_emails_empty_disables_all_admins(self):
        """An empty ADMIN_EMAILS yields no admins."""
        with patch.dict(os.environ, {"ADMIN_EMAILS": ""}, clear=True):
            settings = Settings(_env_file=None)
            assert settings.admin_email_list == []
            assert settings.is_admin_email("anyone@example.com") is False


class TestGetSettings:
    """Test get_settings function."""

    def test_returns_settings_instance(self):
        """Test that get_settings returns a Settings instance."""
        # Clear the cache first
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_caching(self):
        """Test that get_settings returns cached instance."""
        get_settings.cache_clear()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

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
            assert settings.llm_model == "anthropic/claude-sonnet-4-20250514"
            assert settings.cors_origins == ["*"]

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
        """Test default CORS origins."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
            assert "*" in settings.cors_origins

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

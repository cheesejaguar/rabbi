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
            settings = Settings()
            assert settings.app_name == "rebbe.dev"
            assert settings.app_version == "1.0.0"
            assert settings.debug is False
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
            settings = Settings()
            assert settings.app_name == "Test Rabbi"
            assert settings.app_version == "2.0.0"
            assert settings.debug is True
            assert settings.openrouter_api_key == "test-key-123"
            assert settings.openrouter_base_url == "https://custom.openrouter.ai/api/v1"
            assert settings.llm_model == "anthropic/claude-opus-4-20250514"

    def test_cors_origins_default(self):
        """Test default CORS origins."""
        settings = Settings()
        assert "*" in settings.cors_origins


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

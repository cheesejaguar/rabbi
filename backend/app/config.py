"""Application configuration."""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "AI Rabbi"
    app_version: str = "1.0.0"
    debug: bool = False

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"

    cors_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

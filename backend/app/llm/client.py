"""Shared AsyncAnthropic client for the v2 pipeline.

Created lazily so importing the app never requires an API key (tests and
v1-only deployments run without one).
"""

import logging
from typing import Optional

import anthropic

from ..config import get_settings

logger = logging.getLogger(__name__)

# Server-side refusal fallback ("default" routing) for Sonnet 5.5 on the
# Claude API. Haiku has no server-side fallback, so classifier/audit calls
# never send it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: Optional[anthropic.AsyncAnthropic] = None


def is_configured() -> bool:
    return bool(get_settings().anthropic_api_key)


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        settings = get_settings()
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            max_retries=2,
            timeout=anthropic.Timeout(120.0, connect=5.0),
        )
    return _client


def set_client(client) -> None:
    """Test hook: inject a fake client."""
    global _client
    _client = client

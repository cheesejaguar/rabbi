"""Shared client for the v2 pipeline, routed through the AI gateway.

v2 speaks the Anthropic Messages format, sent to Vercel AI Gateway's
Anthropic-compatible endpoint (``https://ai-gateway.vercel.sh``) with the
gateway key, so all model traffic and billing stay on the configured
gateway. Model ids use the gateway's names (``anthropic/claude-sonnet-5.5``).

Created lazily so importing the app never requires a key (tests and
v1-only deployments run without one).
"""

import logging
from typing import Optional

import anthropic

from ..config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[anthropic.AsyncAnthropic] = None


def is_configured() -> bool:
    """v2 needs the Vercel AI Gateway (the only configured gateway with a Messages endpoint)."""
    s = get_settings()
    return s.gateway.lower() == "vercel" and bool(s.ai_gateway_api_key)


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        settings = get_settings()
        _client = anthropic.AsyncAnthropic(
            api_key=settings.ai_gateway_api_key or None,
            base_url=settings.ai_gateway_messages_base_url,
            max_retries=2,
            timeout=anthropic.Timeout(120.0, connect=5.0),
        )
    return _client


def set_client(client) -> None:
    """Test hook: inject a fake client."""
    global _client
    _client = client

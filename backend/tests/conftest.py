"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI client for OpenRouter."""
    client = MagicMock()
    # Set up the chat.completions.create method
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock()
    return client


# Alias for backward compatibility with existing tests
@pytest.fixture
def mock_anthropic_client(mock_openai_client):
    """Alias for mock_openai_client for backward compatibility."""
    return mock_openai_client


@pytest.fixture
def mock_claude_response():
    """Create a mock OpenAI-compatible API response with usage metrics."""
    def _create_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
        response = MagicMock()
        choice = MagicMock()
        message = MagicMock()
        message.content = text
        choice.message = message
        response.choices = [choice]
        # Add usage metrics for cost calculation
        usage = MagicMock()
        usage.prompt_tokens = input_tokens
        usage.completion_tokens = output_tokens
        response.usage = usage
        return response
    return _create_response


@pytest.fixture
def sample_conversation_history():
    """Sample conversation history for testing."""
    return [
        {"role": "user", "content": "Hello, I have a question."},
        {"role": "assistant", "content": "Shalom! I'm here to help."},
    ]


# Sandboxed environments ship a preinstalled Chromium whose build number may
# not match the installed Playwright package. Point pytest-playwright at it
# when present so the browser suites run without `playwright install`.
_PREINSTALLED_CHROMIUM = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="session")
def browser_type_launch_args(pytestconfig):
    import os

    args = {}
    if os.path.exists(_PREINSTALLED_CHROMIUM):
        args["executable_path"] = _PREINSTALLED_CHROMIUM
    headed = pytestconfig.getoption("--headed", default=False)
    if headed:
        args["headless"] = False
    return args

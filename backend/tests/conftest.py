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
    """Create a mock OpenAI-compatible API response."""
    def _create_response(text: str):
        response = MagicMock()
        choice = MagicMock()
        message = MagicMock()
        message.content = text
        choice.message = message
        response.choices = [choice]
        return response
    return _create_response


@pytest.fixture
def sample_conversation_history():
    """Sample conversation history for testing."""
    return [
        {"role": "user", "content": "Hello, I have a question."},
        {"role": "assistant", "content": "Shalom! I'm here to help."},
    ]

"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for OpenRouter."""
    client = MagicMock()
    # Set up the chat.completions.create method
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock()
    return client


# Aliases for backward compatibility with existing tests
@pytest.fixture
def mock_openai_client(mock_llm_client):
    """Alias for mock_llm_client for backward compatibility."""
    return mock_llm_client


@pytest.fixture
def mock_anthropic_client(mock_llm_client):
    """Alias for mock_llm_client for backward compatibility."""
    return mock_llm_client


@pytest.fixture
def mock_claude_response():
    """Create a mock LLM API response with usage metrics."""
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

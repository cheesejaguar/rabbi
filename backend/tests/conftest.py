"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import Mock, MagicMock


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client."""
    client = MagicMock()
    # Set up the messages.create method
    client.messages = MagicMock()
    client.messages.create = MagicMock()
    return client


@pytest.fixture
def mock_claude_response():
    """Create a mock Claude API response."""
    def _create_response(text: str):
        response = MagicMock()
        content_block = MagicMock()
        content_block.text = text
        response.content = [content_block]
        return response
    return _create_response


@pytest.fixture
def sample_conversation_history():
    """Sample conversation history for testing."""
    return [
        {"role": "user", "content": "Hello, I have a question."},
        {"role": "assistant", "content": "Shalom! I'm here to help."},
    ]

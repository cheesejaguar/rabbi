"""Tests for models.py - Pydantic API models."""

import pytest
from pydantic import ValidationError

from app.models import (
    Message,
    ChatRequest,
    ChatResponse,
    GreetingResponse,
    HealthResponse,
)


class TestMessage:
    """Test Message model."""

    def test_valid_message(self):
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_assistant_role(self):
        msg = Message(role="assistant", content="Shalom!")
        assert msg.role == "assistant"

    def test_missing_role_raises(self):
        with pytest.raises(ValidationError):
            Message(content="Hello")

    def test_missing_content_raises(self):
        with pytest.raises(ValidationError):
            Message(role="user")


class TestChatRequest:
    """Test ChatRequest model."""

    def test_minimal_request(self):
        req = ChatRequest(message="What is Shabbat?")
        assert req.message == "What is Shabbat?"
        assert req.conversation_history == []
        assert req.session_id is None

    def test_full_request(self):
        history = [Message(role="user", content="Hi")]
        req = ChatRequest(
            message="Follow-up question",
            conversation_history=history,
            session_id="session-123",
        )
        assert len(req.conversation_history) == 1
        assert req.session_id == "session-123"

    def test_empty_message_raises(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            ChatRequest()


class TestChatResponse:
    """Test ChatResponse model."""

    def test_minimal_response(self):
        resp = ChatResponse(response="This is my answer")
        assert resp.response == "This is my answer"
        assert resp.requires_human_referral is False
        assert resp.session_id is None
        assert resp.metadata == {}

    def test_full_response(self):
        resp = ChatResponse(
            response="Answer",
            requires_human_referral=True,
            session_id="session-456",
            metadata={"pastoral_mode": "counseling"},
        )
        assert resp.requires_human_referral is True
        assert resp.session_id == "session-456"
        assert resp.metadata["pastoral_mode"] == "counseling"


class TestGreetingResponse:
    """Test GreetingResponse model."""

    def test_greeting(self):
        resp = GreetingResponse(greeting="Shalom and welcome!")
        assert resp.greeting == "Shalom and welcome!"

    def test_missing_greeting_raises(self):
        with pytest.raises(ValidationError):
            GreetingResponse()


class TestHealthResponse:
    """Test HealthResponse model."""

    def test_health_response(self):
        resp = HealthResponse(status="healthy", version="1.0.0")
        assert resp.status == "healthy"
        assert resp.version == "1.0.0"

    def test_missing_fields_raises(self):
        with pytest.raises(ValidationError):
            HealthResponse(status="healthy")

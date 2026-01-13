"""Tests for main.py - FastAPI endpoints."""

import pytest
import sys
from unittest.mock import patch, Mock, AsyncMock, MagicMock


@pytest.fixture(scope="module")
def test_app():
    """Create the app with mocked orchestrator and authentication."""
    # Create mock orchestrator before importing app.main
    mock_orchestrator_instance = Mock()
    mock_orchestrator_instance.get_greeting = AsyncMock(
        return_value="Shalom and welcome!"
    )
    mock_orchestrator_instance.process_message = AsyncMock(return_value={
        "response": "Test response",
        "requires_human_referral": False,
        "metadata": {"pastoral_mode": "teaching"},
    })

    # Mock user for authentication
    mock_user = {
        "id": "test-user-id",
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
    }

    # Patch the RabbiOrchestrator class before importing main
    with patch.dict(sys.modules, {}):
        # Clear cached modules
        mods_to_remove = [k for k in sys.modules if k.startswith('app')]
        for mod in mods_to_remove:
            del sys.modules[mod]

        with patch('app.agents.orchestrator.OpenAI'):
            with patch('app.agents.RabbiOrchestrator', return_value=mock_orchestrator_instance):
                # Mock authentication to always return a user
                with patch('app.auth.get_current_user', return_value=mock_user):
                    with patch('app.main.get_current_user', return_value=mock_user):
                        from app.main import app
                        from fastapi.testclient import TestClient
                        client = TestClient(app)
                        yield client, mock_orchestrator_instance, app


@pytest.fixture
def client_and_mock(test_app):
    """Get client and mock orchestrator."""
    client, mock_orch, app = test_app
    # Reset mock for each test
    mock_orch.process_message.reset_mock()
    return client, mock_orch


class TestHealthEndpoint:
    """Test /api/health endpoint."""

    def test_health_check(self, client_and_mock):
        client, _ = client_and_mock
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestGreetingEndpoint:
    """Test /api/greeting endpoint."""

    def test_get_greeting(self, client_and_mock):
        client, mock_orch = client_and_mock
        response = client.get("/api/greeting")

        assert response.status_code == 200
        data = response.json()
        assert "greeting" in data
        # The greeting comes from the real orchestrator's get_greeting method
        assert "Shalom" in data["greeting"]


class TestChatEndpoint:
    """Test /api/chat endpoint."""

    def test_chat_simple_message(self, client_and_mock):
        client, mock_orch = client_and_mock
        mock_orch.process_message = AsyncMock(return_value={
            "response": "Shalom! Shabbat is the Jewish day of rest.",
            "requires_human_referral": False,
            "metadata": {"pastoral_mode": "teaching", "vulnerability_detected": False},
        })

        response = client.post(
            "/api/chat",
            json={"message": "What is Shabbat?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "session_id" in data
        assert data["requires_human_referral"] is False

    def test_chat_with_session_id(self, client_and_mock):
        client, mock_orch = client_and_mock
        mock_orch.process_message = AsyncMock(return_value={
            "response": "Response",
            "requires_human_referral": False,
            "metadata": {},
        })

        response = client.post(
            "/api/chat",
            json={
                "message": "Question",
                "session_id": "existing-session-123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "existing-session-123"

    def test_chat_with_conversation_history(self, client_and_mock):
        client, mock_orch = client_and_mock
        mock_orch.process_message = AsyncMock(return_value={
            "response": "Follow-up response",
            "requires_human_referral": False,
            "metadata": {},
        })

        response = client.post(
            "/api/chat",
            json={
                "message": "Follow-up question",
                "conversation_history": [
                    {"role": "user", "content": "First question"},
                    {"role": "assistant", "content": "First answer"},
                ],
            },
        )

        assert response.status_code == 200

    def test_chat_empty_message_fails(self, client_and_mock):
        client, _ = client_and_mock
        response = client.post(
            "/api/chat",
            json={"message": ""},
        )

        assert response.status_code == 422

    def test_chat_missing_message_fails(self, client_and_mock):
        client, _ = client_and_mock
        response = client.post(
            "/api/chat",
            json={},
        )

        assert response.status_code == 422

    def test_chat_error_handling(self, client_and_mock):
        client, mock_orch = client_and_mock
        mock_orch.process_message = AsyncMock(side_effect=Exception("API Error"))

        response = client.post(
            "/api/chat",
            json={"message": "Test question"},
        )

        assert response.status_code == 500
        assert "error" in response.json()["detail"].lower()


class TestCORSMiddleware:
    """Test CORS middleware configuration."""

    def test_cors_headers_present(self, client_and_mock):
        client, _ = client_and_mock
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:8613",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code == 200


class TestAppMetadata:
    """Test app metadata."""

    def test_app_has_description(self, test_app):
        _, _, app = test_app
        assert app.description is not None
        assert "progressive Modern Orthodox" in app.description

    def test_app_has_title(self, test_app):
        _, _, app = test_app
        assert app.title is not None

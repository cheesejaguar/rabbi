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


class TestChatStreamEndpoint:
    """Test /api/chat/stream endpoint - credit handling and error safety.

    ``StreamingResponse`` always returns HTTP 200; success/failure is
    signalled inside the SSE body via ``{"type": "..."}`` events, so these
    tests assert on ``response.text`` rather than the status code.
    """

    async def _token_stream(self, tokens=("Hello",)):
        for t in tokens:
            yield {"type": "token", "data": t}

    def test_credit_check_failure_fails_closed(self, client_and_mock):
        """If consume_credit() raises, the chat must be blocked, not given away for free."""
        client, mock_orch = client_and_mock
        mock_orch.process_message_stream = lambda **kwargs: self._token_stream()

        import app.main as main_module
        with patch.object(main_module.settings, 'database_url', 'postgresql://test/db'):
            with patch('app.main.db.get_user_profile', new=AsyncMock(return_value=None)):
                with patch(
                    'app.main.db.consume_credit',
                    new=AsyncMock(side_effect=RuntimeError("db unavailable")),
                ) as mock_consume:
                    response = client.post("/api/chat/stream", json={"message": "Hello"})

        assert response.status_code == 200
        body = response.text
        assert '"type": "error"' in body
        # The orchestrator must never have been reached - no token events emitted.
        assert '"type": "token"' not in body
        mock_consume.assert_called_once()

    def test_no_credits_remaining_blocks_chat(self, client_and_mock):
        """Existing behavior: a False return from consume_credit blocks the chat."""
        client, mock_orch = client_and_mock
        mock_orch.process_message_stream = lambda **kwargs: self._token_stream()

        import app.main as main_module
        with patch.object(main_module.settings, 'database_url', 'postgresql://test/db'):
            with patch('app.main.db.get_user_profile', new=AsyncMock(return_value=None)):
                with patch('app.main.db.consume_credit', new=AsyncMock(return_value=False)):
                    response = client.post("/api/chat/stream", json={"message": "Hello"})

        assert response.status_code == 200
        body = response.text
        assert "No credits remaining" in body
        assert '"type": "token"' not in body

    def test_successful_credit_consumption_allows_chat(self, client_and_mock):
        """A credit is consumed and the orchestrator stream is delivered."""
        client, mock_orch = client_and_mock
        mock_orch.process_message_stream = lambda **kwargs: self._token_stream(("Shalom",))

        import app.main as main_module
        with patch.object(main_module.settings, 'database_url', 'postgresql://test/db'):
            with patch('app.main.db.get_user_profile', new=AsyncMock(return_value=None)):
                with patch('app.main.db.consume_credit', new=AsyncMock(return_value=True)):
                    with patch('app.main.db.add_message', new=AsyncMock(return_value=None)):
                        with patch('app.main.db.get_conversation', new=AsyncMock(return_value=None)):
                            response = client.post("/api/chat/stream", json={"message": "Hello"})

        assert response.status_code == 200
        body = response.text
        assert '"type": "token"' in body
        assert "Shalom" in body

    def test_stream_failure_refunds_consumed_credit(self, client_and_mock):
        """If a credit was consumed but the pipeline then fails, refund it."""
        client, mock_orch = client_and_mock

        async def _failing_stream(**kwargs):
            raise RuntimeError("pipeline exploded")
            yield  # pragma: no cover - makes this an async generator

        mock_orch.process_message_stream = _failing_stream

        import app.main as main_module
        with patch.object(main_module.settings, 'database_url', 'postgresql://test/db'):
            with patch('app.main.db.get_user_profile', new=AsyncMock(return_value=None)):
                with patch('app.main.db.consume_credit', new=AsyncMock(return_value=True)):
                    with patch('app.main.db.add_credits', new=AsyncMock(return_value=5)) as mock_refund:
                        with patch('app.main.db.log_error', new=AsyncMock(return_value=None)):
                            response = client.post("/api/chat/stream", json={"message": "Hello"})

        assert response.status_code == 200
        assert '"type": "error"' in response.text
        # No raw exception text should leak into the SSE payload.
        assert "pipeline exploded" not in response.text
        mock_refund.assert_called_once_with("test-user-id", 1)


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

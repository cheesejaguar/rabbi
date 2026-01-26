"""Tests for conversations.py - Conversations API endpoints."""

import pytest
import sys
import os
from unittest.mock import patch, AsyncMock, MagicMock, Mock


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return {
        "id": "user-123",
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
    }


@pytest.fixture(scope="module")
def app_with_mocks():
    """Create the app with mocked orchestrator."""
    # Create mock orchestrator before importing app.main
    mock_orchestrator_instance = Mock()
    mock_orchestrator_instance.get_greeting = AsyncMock(return_value="Shalom!")
    mock_orchestrator_instance.process_message = AsyncMock(return_value={
        "response": "Test response",
        "requires_human_referral": False,
        "metadata": {},
    })

    # Set a dummy API key to prevent LLM client initialization errors
    # and patch the orchestrator class
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key-for-testing"}):
        with patch('app.agents.orchestrator.LLMClient'):
            with patch('app.agents.RabbiOrchestrator', return_value=mock_orchestrator_instance):
                # Clear settings cache to pick up the test API key
                from app.config import get_settings
                get_settings.cache_clear()

                from app.main import app
                yield app

                # Clear settings cache again after tests
                get_settings.cache_clear()


@pytest.fixture
def test_client(app_with_mocks, mock_user):
    """Create test client with mocked auth and database."""
    from fastapi.testclient import TestClient
    with patch('app.auth.get_current_user', return_value=mock_user):
        with patch('app.main.get_current_user', return_value=mock_user):
            with patch('app.conversations.get_current_user', return_value=mock_user):
                yield TestClient(app_with_mocks)


class TestListConversations:
    """Test GET /api/conversations endpoint."""

    def test_list_conversations_success(self, test_client, mock_user):
        """Test listing conversations returns list."""
        mock_conversations = [
            {"id": "conv-1", "title": "First", "created_at": "2024-01-01", "updated_at": "2024-01-01", "first_message": "Hello"},
            {"id": "conv-2", "title": "Second", "created_at": "2024-01-02", "updated_at": "2024-01-02", "first_message": "Hi"},
        ]

        with patch('app.conversations.db.list_conversations', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_conversations

            response = test_client.get("/api/conversations")

            assert response.status_code == 200
            data = response.json()
            assert "conversations" in data
            assert len(data["conversations"]) == 2

    def test_list_conversations_empty(self, test_client, mock_user):
        """Test listing when no conversations exist."""
        with patch('app.conversations.db.list_conversations', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []

            response = test_client.get("/api/conversations")

            assert response.status_code == 200
            data = response.json()
            assert data["conversations"] == []

    def test_list_conversations_with_pagination(self, test_client, mock_user):
        """Test listing with limit and offset parameters."""
        with patch('app.conversations.db.list_conversations', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []

            response = test_client.get("/api/conversations?limit=10&offset=5")

            assert response.status_code == 200
            mock_list.assert_called_once_with(mock_user["id"], 10, 5)

    def test_list_conversations_db_not_configured(self, test_client, mock_user):
        """Test graceful handling when database not configured."""
        with patch('app.conversations.db.list_conversations', new_callable=AsyncMock) as mock_list:
            mock_list.side_effect = RuntimeError("Database URL not configured")

            response = test_client.get("/api/conversations")

            assert response.status_code == 200
            data = response.json()
            assert data["conversations"] == []
            assert "warning" in data

    def test_list_conversations_unauthenticated(self, app_with_mocks):
        """Test that unauthenticated requests are rejected."""
        from fastapi.testclient import TestClient
        with patch('app.auth.get_current_user', return_value=None):
            with patch('app.main.get_current_user', return_value=None):
                with patch('app.conversations.get_current_user', return_value=None):
                    client = TestClient(app_with_mocks)
                    response = client.get("/api/conversations")
                    # Should redirect or return 401
                    assert response.status_code in [401, 302]


class TestCreateConversation:
    """Test POST /api/conversations endpoint."""

    def test_create_conversation_success(self, test_client, mock_user):
        """Test creating a new conversation."""
        mock_conv = {
            "id": "conv-new",
            "user_id": mock_user["id"],
            "title": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }

        with patch('app.conversations.db.upsert_user', new_callable=AsyncMock):
            with patch('app.conversations.db.create_conversation', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_conv

                response = test_client.post("/api/conversations", json={})

                assert response.status_code == 200
                data = response.json()
                assert data["id"] == "conv-new"

    def test_create_conversation_with_title(self, test_client, mock_user):
        """Test creating a conversation with a title."""
        mock_conv = {
            "id": "conv-new",
            "user_id": mock_user["id"],
            "title": "My Conversation",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }

        with patch('app.conversations.db.upsert_user', new_callable=AsyncMock):
            with patch('app.conversations.db.create_conversation', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_conv

                response = test_client.post(
                    "/api/conversations",
                    json={"title": "My Conversation"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["title"] == "My Conversation"

    def test_create_conversation_upserts_user(self, test_client, mock_user):
        """Test that creating a conversation upserts the user first."""
        mock_conv = {"id": "conv-new", "user_id": mock_user["id"], "title": None, "created_at": "2024-01-01", "updated_at": "2024-01-01"}

        with patch('app.conversations.db.upsert_user', new_callable=AsyncMock) as mock_upsert:
            with patch('app.conversations.db.create_conversation', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_conv

                response = test_client.post("/api/conversations", json={})

                assert response.status_code == 200
                mock_upsert.assert_called_once()

    def test_create_conversation_db_not_configured(self, test_client, mock_user):
        """Test error when database not configured."""
        with patch('app.conversations.db.upsert_user', new_callable=AsyncMock) as mock_upsert:
            mock_upsert.side_effect = RuntimeError("Database URL not configured")

            response = test_client.post("/api/conversations", json={})

            assert response.status_code == 503


class TestGetConversation:
    """Test GET /api/conversations/{id} endpoint."""

    def test_get_conversation_success(self, test_client, mock_user):
        """Test getting a conversation with messages."""
        mock_conv = {
            "id": "conv-123",
            "user_id": mock_user["id"],
            "title": "Test Conversation",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_messages = [
            {"id": "msg-1", "role": "user", "content": "Hello", "created_at": "2024-01-01T00:00:00Z"},
            {"id": "msg-2", "role": "assistant", "content": "Shalom!", "created_at": "2024-01-01T00:00:01Z"},
        ]

        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            with patch('app.conversations.db.get_messages', new_callable=AsyncMock) as mock_msgs:
                mock_get.return_value = mock_conv
                mock_msgs.return_value = mock_messages

                response = test_client.get("/api/conversations/conv-123")

                assert response.status_code == 200
                data = response.json()
                assert data["id"] == "conv-123"
                assert len(data["messages"]) == 2

    def test_get_conversation_not_found(self, test_client, mock_user):
        """Test getting a non-existent conversation."""
        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            response = test_client.get("/api/conversations/nonexistent")

            assert response.status_code == 404

    def test_get_conversation_wrong_user(self, test_client, mock_user):
        """Test that users can only get their own conversations."""
        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            # Returns None because conversation belongs to different user
            mock_get.return_value = None

            response = test_client.get("/api/conversations/other-user-conv")

            assert response.status_code == 404


class TestUpdateConversation:
    """Test PATCH /api/conversations/{id} endpoint."""

    def test_update_conversation_success(self, test_client, mock_user):
        """Test updating a conversation title."""
        mock_conv = {
            "id": "conv-123",
            "user_id": mock_user["id"],
            "title": "Updated Title",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }

        with patch('app.conversations.db.update_conversation', new_callable=AsyncMock) as mock_update:
            mock_update.return_value = mock_conv

            response = test_client.patch(
                "/api/conversations/conv-123",
                json={"title": "Updated Title"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["title"] == "Updated Title"

    def test_update_conversation_not_found(self, test_client, mock_user):
        """Test updating a non-existent conversation."""
        with patch('app.conversations.db.update_conversation', new_callable=AsyncMock) as mock_update:
            mock_update.return_value = None

            response = test_client.patch(
                "/api/conversations/nonexistent",
                json={"title": "New Title"}
            )

            assert response.status_code == 404

    def test_update_conversation_missing_title(self, test_client, mock_user):
        """Test that title is required for update."""
        response = test_client.patch(
            "/api/conversations/conv-123",
            json={}
        )

        assert response.status_code == 422


class TestDeleteConversation:
    """Test DELETE /api/conversations/{id} endpoint."""

    def test_delete_conversation_success(self, test_client, mock_user):
        """Test deleting a conversation."""
        with patch('app.conversations.db.delete_conversation', new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = True

            response = test_client.delete("/api/conversations/conv-123")

            assert response.status_code == 200
            data = response.json()
            assert data["deleted"] is True

    def test_delete_conversation_not_found(self, test_client, mock_user):
        """Test deleting a non-existent conversation."""
        with patch('app.conversations.db.delete_conversation', new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = False

            response = test_client.delete("/api/conversations/nonexistent")

            assert response.status_code == 404


class TestAddMessage:
    """Test POST /api/conversations/{id}/messages endpoint."""

    def test_add_message_success(self, test_client, mock_user):
        """Test adding a message to a conversation."""
        mock_conv = {"id": "conv-123", "user_id": mock_user["id"], "title": "Test", "created_at": "2024-01-01", "updated_at": "2024-01-01"}
        mock_msg = {
            "id": "msg-new",
            "conversation_id": "conv-123",
            "role": "user",
            "content": "Hello!",
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
        }

        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            with patch('app.conversations.db.add_message', new_callable=AsyncMock) as mock_add:
                with patch('app.conversations.db.generate_conversation_title', new_callable=AsyncMock) as mock_title:
                    with patch('app.conversations.db.update_conversation', new_callable=AsyncMock):
                        mock_get.return_value = mock_conv
                        mock_add.return_value = mock_msg
                        mock_title.return_value = "Hello!"

                        response = test_client.post(
                            "/api/conversations/conv-123/messages",
                            json={"role": "user", "content": "Hello!"}
                        )

                        assert response.status_code == 200
                        data = response.json()
                        assert data["content"] == "Hello!"

    def test_add_message_conversation_not_found(self, test_client, mock_user):
        """Test adding a message to non-existent conversation."""
        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            response = test_client.post(
                "/api/conversations/nonexistent/messages",
                json={"role": "user", "content": "Hello!"}
            )

            assert response.status_code == 404

    def test_add_message_generates_title(self, test_client, mock_user):
        """Test that first user message generates title."""
        mock_conv = {"id": "conv-123", "user_id": mock_user["id"], "title": None, "created_at": "2024-01-01", "updated_at": "2024-01-01"}
        mock_msg = {"id": "msg-new", "conversation_id": "conv-123", "role": "user", "content": "What is Shabbat?", "metadata": {}, "created_at": "2024-01-01"}

        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            with patch('app.conversations.db.add_message', new_callable=AsyncMock) as mock_add:
                with patch('app.conversations.db.generate_conversation_title', new_callable=AsyncMock) as mock_title:
                    with patch('app.conversations.db.update_conversation', new_callable=AsyncMock) as mock_update:
                        mock_get.return_value = mock_conv
                        mock_add.return_value = mock_msg
                        mock_title.return_value = "What is Shabbat?"

                        response = test_client.post(
                            "/api/conversations/conv-123/messages",
                            json={"role": "user", "content": "What is Shabbat?"}
                        )

                        assert response.status_code == 200
                        mock_title.assert_called_once()
                        mock_update.assert_called_once()


class TestGetMessages:
    """Test GET /api/conversations/{id}/messages endpoint."""

    def test_get_messages_success(self, test_client, mock_user):
        """Test getting messages for a conversation."""
        mock_conv = {"id": "conv-123", "user_id": mock_user["id"], "title": "Test", "created_at": "2024-01-01", "updated_at": "2024-01-01"}
        mock_messages = [
            {"id": "msg-1", "role": "user", "content": "Hello", "created_at": "2024-01-01"},
            {"id": "msg-2", "role": "assistant", "content": "Shalom!", "created_at": "2024-01-01"},
        ]

        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            with patch('app.conversations.db.get_messages', new_callable=AsyncMock) as mock_msgs:
                mock_get.return_value = mock_conv
                mock_msgs.return_value = mock_messages

                response = test_client.get("/api/conversations/conv-123/messages")

                assert response.status_code == 200
                data = response.json()
                assert len(data["messages"]) == 2

    def test_get_messages_conversation_not_found(self, test_client, mock_user):
        """Test getting messages for non-existent conversation."""
        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            response = test_client.get("/api/conversations/nonexistent/messages")

            assert response.status_code == 404

    def test_get_messages_with_limit(self, test_client, mock_user):
        """Test getting messages with limit parameter."""
        mock_conv = {"id": "conv-123", "user_id": mock_user["id"], "title": "Test", "created_at": "2024-01-01", "updated_at": "2024-01-01"}

        with patch('app.conversations.db.get_conversation', new_callable=AsyncMock) as mock_get:
            with patch('app.conversations.db.get_messages', new_callable=AsyncMock) as mock_msgs:
                mock_get.return_value = mock_conv
                mock_msgs.return_value = []

                response = test_client.get("/api/conversations/conv-123/messages?limit=50")

                assert response.status_code == 200
                mock_msgs.assert_called_once_with("conv-123", 50)

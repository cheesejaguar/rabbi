"""Tests for conversations.py - Conversations API endpoints.

Requests go through the real app with a real signed session cookie, and the
endpoints read and write a real PostgreSQL database (see the ``live_db``
fixture in conftest.py).
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.auth import create_session_token
from app.main import app


USER = {
    "id": "user-123",
    "email": "test@example.com",
    "first_name": "Test",
    "last_name": "User",
}

OTHER_USER = {
    "id": "user-456",
    "email": "other@example.com",
    "first_name": "Other",
    "last_name": "Person",
}


def _set_db_url(monkeypatch, url):
    from app.config import get_settings

    for settings in {id(s): s for s in (get_settings(), main_module.settings)}.values():
        monkeypatch.setattr(settings, "database_url", url)
        monkeypatch.setattr(settings, "postgres_url", "")
        monkeypatch.setattr(settings, "pghost", "")
        monkeypatch.setattr(settings, "postgres_host", "")


@pytest.fixture
def client(live_db, pg_url, monkeypatch):
    """Client authenticated as USER, backed by the real test database."""
    _set_db_url(monkeypatch, pg_url)
    with TestClient(app) as c:
        c.cookies.set("session", create_session_token(USER))
        c.portal.call(live_db.upsert_user, USER["id"], USER["email"], USER["first_name"], USER["last_name"])
        c.portal.call(live_db.upsert_user, OTHER_USER["id"], OTHER_USER["email"])
        c.db = live_db
        yield c


@pytest.fixture
def no_db_client(monkeypatch):
    """Client authenticated as USER with no database configured."""
    _set_db_url(monkeypatch, "")
    c = TestClient(app)
    c.cookies.set("session", create_session_token(USER))
    return c


def _seed_conversation(client, user_id=USER["id"], title=None, messages=()):
    conv = client.portal.call(client.db.create_conversation, user_id, title)
    for role, content in messages:
        client.portal.call(client.db.add_message, conv["id"], role, content)
    return conv


class TestListConversations:
    """Test GET /api/conversations endpoint."""

    def test_list_conversations_success(self, client):
        """Lists only the user's conversations, with a first-message preview."""
        _seed_conversation(client, title="First", messages=[("user", "Hello")])
        _seed_conversation(client, title="Second", messages=[("user", "Hi"), ("assistant", "Shalom")])
        _seed_conversation(client, user_id=OTHER_USER["id"], title="Not mine")

        response = client.get("/api/conversations")

        assert response.status_code == 200
        conversations = response.json()["conversations"]
        assert sorted(c["title"] for c in conversations) == ["First", "Second"]
        previews = {c["title"]: c["first_message"] for c in conversations}
        assert previews == {"First": "Hello", "Second": "Hi"}

    def test_list_conversations_empty(self, client):
        """Test listing when no conversations exist."""
        response = client.get("/api/conversations")

        assert response.status_code == 200
        assert response.json()["conversations"] == []

    def test_list_conversations_with_pagination(self, client):
        """limit and offset page through the user's conversations."""
        for i in range(4):
            _seed_conversation(client, title=f"c{i}")

        first = client.get("/api/conversations?limit=2&offset=0").json()["conversations"]
        rest = client.get("/api/conversations?limit=2&offset=2").json()["conversations"]

        assert len(first) == 2 and len(rest) == 2
        assert {c["id"] for c in first}.isdisjoint({c["id"] for c in rest})

    def test_list_conversations_db_not_configured(self, no_db_client):
        """Test graceful handling when database not configured."""
        response = no_db_client.get("/api/conversations")

        assert response.status_code == 200
        data = response.json()
        assert data["conversations"] == []
        assert data["warning"] == "Database not configured"

    def test_list_conversations_unauthenticated(self, monkeypatch):
        """Test that unauthenticated requests are rejected."""
        _set_db_url(monkeypatch, "")
        response = TestClient(app).get("/api/conversations")
        assert response.status_code == 401


class TestCreateConversation:
    """Test POST /api/conversations endpoint."""

    def test_create_conversation_success(self, client):
        """Test creating a new conversation."""
        response = client.post("/api/conversations", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == USER["id"]
        assert data["title"] is None
        assert client.portal.call(client.db.get_conversation, data["id"], USER["id"]) is not None

    def test_create_conversation_with_title(self, client):
        """Test creating a conversation with a title."""
        response = client.post("/api/conversations", json={"title": "My Conversation"})

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "My Conversation"
        stored = client.portal.call(client.db.get_conversation, data["id"], USER["id"])
        assert stored["title"] == "My Conversation"

    def test_create_conversation_upserts_user(self, client):
        """A signed-in user with no user row yet gets one before the conversation."""
        new_user = {"id": "brand-new", "email": "new@example.com", "first_name": "New", "last_name": "Comer"}
        client.cookies.set("session", create_session_token(new_user))

        response = client.post("/api/conversations", json={})

        assert response.status_code == 200
        stored = client.portal.call(client.db.get_user, "brand-new")
        assert stored["email"] == "new@example.com"
        assert stored["first_name"] == "New"

    def test_create_conversation_db_not_configured(self, no_db_client):
        """Test error when database not configured."""
        response = no_db_client.post("/api/conversations", json={})

        assert response.status_code == 503


class TestGetConversation:
    """Test GET /api/conversations/{id} endpoint."""

    def test_get_conversation_success(self, client):
        """Test getting a conversation with messages."""
        conv = _seed_conversation(
            client, title="Test Conversation", messages=[("user", "Hello"), ("assistant", "Shalom!")])

        response = client.get(f"/api/conversations/{conv['id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conv["id"]
        assert data["title"] == "Test Conversation"
        assert [(m["role"], m["content"]) for m in data["messages"]] == [
            ("user", "Hello"), ("assistant", "Shalom!")]

    def test_get_conversation_not_found(self, client):
        """Test getting a non-existent conversation."""
        response = client.get("/api/conversations/nonexistent")

        assert response.status_code == 404

    def test_get_conversation_wrong_user(self, client):
        """Test that users can only get their own conversations."""
        theirs = _seed_conversation(client, user_id=OTHER_USER["id"], messages=[("user", "private")])

        response = client.get(f"/api/conversations/{theirs['id']}")

        assert response.status_code == 404
        assert "private" not in response.text


class TestUpdateConversation:
    """Test PATCH /api/conversations/{id} endpoint."""

    def test_update_conversation_success(self, client):
        """Test updating a conversation title."""
        conv = _seed_conversation(client, title="Old")

        response = client.patch(f"/api/conversations/{conv['id']}", json={"title": "Updated Title"})

        assert response.status_code == 200
        assert response.json()["title"] == "Updated Title"
        stored = client.portal.call(client.db.get_conversation, conv["id"], USER["id"])
        assert stored["title"] == "Updated Title"

    def test_update_conversation_not_found(self, client):
        """Test updating a non-existent conversation."""
        response = client.patch("/api/conversations/nonexistent", json={"title": "New Title"})

        assert response.status_code == 404

    def test_update_other_users_conversation_is_404_and_unchanged(self, client):
        theirs = _seed_conversation(client, user_id=OTHER_USER["id"], title="Theirs")

        response = client.patch(f"/api/conversations/{theirs['id']}", json={"title": "Hijacked"})

        assert response.status_code == 404
        stored = client.portal.call(client.db.get_conversation, theirs["id"], OTHER_USER["id"])
        assert stored["title"] == "Theirs"

    def test_update_conversation_missing_title(self, client):
        """Test that title is required for update."""
        conv = _seed_conversation(client, title="Keep")

        response = client.patch(f"/api/conversations/{conv['id']}", json={})

        assert response.status_code == 422


class TestDeleteConversation:
    """Test DELETE /api/conversations/{id} endpoint."""

    def test_delete_conversation_success(self, client):
        """Deleting removes the conversation and its messages."""
        conv = _seed_conversation(client, messages=[("user", "Hello")])

        response = client.delete(f"/api/conversations/{conv['id']}")

        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert client.portal.call(client.db.get_conversation, conv["id"], USER["id"]) is None
        assert client.portal.call(client.db.get_messages, conv["id"]) == []

    def test_delete_conversation_not_found(self, client):
        """Test deleting a non-existent conversation."""
        response = client.delete("/api/conversations/nonexistent")

        assert response.status_code == 404

    def test_delete_other_users_conversation_is_404_and_kept(self, client):
        theirs = _seed_conversation(client, user_id=OTHER_USER["id"])

        response = client.delete(f"/api/conversations/{theirs['id']}")

        assert response.status_code == 404
        assert client.portal.call(client.db.get_conversation, theirs["id"], OTHER_USER["id"]) is not None


class TestAddMessage:
    """Test POST /api/conversations/{id}/messages endpoint."""

    def test_add_message_success(self, client):
        """Test adding a message to a conversation."""
        conv = _seed_conversation(client, title="Test")

        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"role": "user", "content": "Hello!", "metadata": {"source": "test"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Hello!"
        assert data["conversation_id"] == conv["id"]
        [stored] = client.portal.call(client.db.get_messages, conv["id"])
        assert stored["content"] == "Hello!"
        assert stored["metadata"] == {"source": "test"}

    def test_add_message_conversation_not_found(self, client):
        """Test adding a message to non-existent conversation."""
        response = client.post(
            "/api/conversations/nonexistent/messages",
            json={"role": "user", "content": "Hello!"},
        )

        assert response.status_code == 404

    def test_add_message_to_other_users_conversation_is_rejected(self, client):
        theirs = _seed_conversation(client, user_id=OTHER_USER["id"])

        response = client.post(
            f"/api/conversations/{theirs['id']}/messages",
            json={"role": "user", "content": "sneaky"},
        )

        assert response.status_code == 404
        assert client.portal.call(client.db.get_messages, theirs["id"]) == []

    def test_add_message_generates_title(self, client):
        """The first user message titles an untitled conversation."""
        conv = _seed_conversation(client)

        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"role": "user", "content": "What is Shabbat?\nI am new to this."},
        )

        assert response.status_code == 200
        stored = client.portal.call(client.db.get_conversation, conv["id"], USER["id"])
        assert stored["title"] == "What is Shabbat?..."

    def test_add_message_keeps_existing_title(self, client):
        conv = _seed_conversation(client, title="Chosen title")

        client.post(f"/api/conversations/{conv['id']}/messages", json={"role": "user", "content": "Hi"})

        stored = client.portal.call(client.db.get_conversation, conv["id"], USER["id"])
        assert stored["title"] == "Chosen title"


class TestGetMessages:
    """Test GET /api/conversations/{id}/messages endpoint."""

    def test_get_messages_success(self, client):
        """Test getting messages for a conversation."""
        conv = _seed_conversation(client, messages=[("user", "Hello"), ("assistant", "Shalom!")])

        response = client.get(f"/api/conversations/{conv['id']}/messages")

        assert response.status_code == 200
        assert [m["content"] for m in response.json()["messages"]] == ["Hello", "Shalom!"]

    def test_get_messages_conversation_not_found(self, client):
        """Test getting messages for non-existent conversation."""
        response = client.get("/api/conversations/nonexistent/messages")

        assert response.status_code == 404

    def test_get_messages_with_limit(self, client):
        """limit caps the number of messages returned, oldest first."""
        conv = _seed_conversation(client, messages=[("user", f"m{i}") for i in range(5)])

        response = client.get(f"/api/conversations/{conv['id']}/messages?limit=3")

        assert response.status_code == 200
        assert [m["content"] for m in response.json()["messages"]] == ["m0", "m1", "m2"]

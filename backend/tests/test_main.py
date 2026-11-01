"""Tests for main.py - FastAPI endpoints.

The real app, orchestrator and agents run end to end. Only the LLM provider
client is replaced (``FakeLLM``), and the database is the real test
PostgreSQL (``live_db``).
"""

import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.auth import create_session_token
from app.main import app

USER = {"id": "test-user-id", "email": "test@example.com", "first_name": "Test", "last_name": "User"}


class FakeLLM:
    """OpenAI-compatible client double for the orchestrator's agents.

    Non-streaming calls (pastoral, halachic, moral agents) get ``reply``;
    streaming calls (the voice agent) get ``stream_chunks``, then optionally
    raise ``stream_error``.
    """

    def __init__(self, reply="{}", stream_chunks=("Shalom", " friend."), stream_error=None, error=None):
        self.reply, self.stream_chunks = reply, stream_chunks
        self.stream_error, self.error = stream_error, error
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if kwargs.get("stream"):
            return self._stream()
        return NS(choices=[NS(message=NS(content=self.reply))],
                  usage=NS(prompt_tokens=10, completion_tokens=5))

    def _stream(self):
        for text in self.stream_chunks:
            yield NS(choices=[NS(delta=NS(content=text))], usage=None)
        if self.stream_error:
            raise self.stream_error
        yield NS(choices=[], usage=NS(prompt_tokens=10, completion_tokens=5))


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    app.state.limiter.reset()
    yield


@pytest.fixture
def llm(monkeypatch):
    """Install a FakeLLM as the provider client of every orchestrator agent."""
    fake = FakeLLM()
    orch = main_module.orchestrator
    for holder in (orch, orch.pastoral_agent, orch.halachic_agent, orch.moral_agent, orch.voice_agent):
        monkeypatch.setattr(holder, "client", fake)
    return fake


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def signed_in():
    """Signed-in client (real session cookie), no database configured."""
    with TestClient(app) as c:
        c.cookies.set("session", create_session_token(USER))
        yield c


@pytest.fixture
def user_client(live_db):
    """Signed-in client (real session cookie) backed by the real test DB."""
    with TestClient(app) as c:
        c.portal.call(live_db.upsert_user, USER["id"], USER["email"], USER["first_name"], USER["last_name"])
        c.cookies.set("session", create_session_token(USER))
        yield c


def events(body):
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def credits(c, db):
    return c.portal.call(db.get_user_credits, USER["id"])


class TestHealthEndpoint:
    """Test /api/health endpoint."""

    def test_health_check(self, client):
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == app.version


class TestGreetingEndpoint:
    """Test /api/greeting endpoint."""

    def test_get_greeting(self, client):
        response = client.get("/api/greeting")

        assert response.status_code == 200
        greeting = response.json()["greeting"]
        # The greeting comes from the real orchestrator's get_greeting method
        assert greeting.startswith("Shalom and welcome.")
        assert "I'm an AI" in greeting


class TestChatEndpoint:
    """Test /api/chat endpoint (non-streaming v1 pipeline)."""

    def test_chat_simple_message(self, signed_in, llm):
        llm.reply = "Shabbat is the Jewish day of rest."
        response = signed_in.post("/api/chat", json={"message": "What is Shabbat?"})

        assert response.status_code == 200
        data = response.json()
        assert data["response"] == "Shabbat is the Jewish day of rest."
        assert data["requires_human_referral"] is False
        assert data["session_id"]
        # The user's question reached the provider.
        assert any("What is Shabbat?" in json.dumps(c["messages"]) for c in llm.calls)

    def test_chat_with_session_id(self, signed_in, llm):
        response = signed_in.post("/api/chat", json={"message": "Question", "session_id": "existing-session-123"})

        assert response.status_code == 200
        assert response.json()["session_id"] == "existing-session-123"

    def test_chat_with_conversation_history(self, signed_in, llm):
        response = signed_in.post(
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
        # Prior turns are forwarded to the model.
        sent = json.dumps(llm.calls[-1]["messages"])
        assert "First question" in sent and "First answer" in sent

    def test_chat_requires_sign_in(self, client, llm):
        assert client.post("/api/chat", json={"message": "Hi"}).status_code == 401
        assert llm.calls == []

    def test_chat_empty_message_fails(self, signed_in):
        assert signed_in.post("/api/chat", json={"message": ""}).status_code == 422

    def test_chat_missing_message_fails(self, signed_in):
        assert signed_in.post("/api/chat", json={}).status_code == 422

    def test_chat_error_handling(self, signed_in, llm):
        llm.error = RuntimeError("API Error from provider")

        response = signed_in.post("/api/chat", json={"message": "Test question"})

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail == "An error occurred processing your message. Please try again."
        assert "API Error" not in detail


class TestChatStreamEndpoint:
    """Test /api/chat/stream endpoint - credit handling and error safety.

    ``StreamingResponse`` always returns HTTP 200; success/failure is
    signalled inside the SSE body via ``{"type": "..."}`` events.
    """

    def test_credit_check_failure_fails_closed(self, user_client, live_db, llm):
        """If consume_credit() raises, the chat must be blocked, not given away for free."""

        async def break_credit_updates():
            async with live_db.get_connection() as conn:
                await conn.execute("""
                    CREATE FUNCTION fail_credit_update() RETURNS trigger AS $$
                    BEGIN RAISE EXCEPTION 'db unavailable'; END $$ LANGUAGE plpgsql;
                    CREATE TRIGGER fail_credit_update BEFORE UPDATE ON users
                    FOR EACH ROW EXECUTE FUNCTION fail_credit_update();
                """)

        async def restore():
            async with live_db.get_connection() as conn:
                await conn.execute("DROP TRIGGER fail_credit_update ON users; DROP FUNCTION fail_credit_update();")

        before = credits(user_client, live_db)
        user_client.portal.call(break_credit_updates)
        try:
            response = user_client.post("/api/chat/stream", json={"message": "Hello"})
        finally:
            user_client.portal.call(restore)

        assert response.status_code == 200
        types = [e["type"] for e in events(response.text)]
        assert types == ["error"]
        assert llm.calls == []  # the model was never reached
        assert credits(user_client, live_db) == before

    def test_no_credits_remaining_blocks_chat(self, user_client, live_db, llm):
        user_client.portal.call(live_db.add_credits, USER["id"], -credits(user_client, live_db))

        response = user_client.post("/api/chat/stream", json={"message": "Hello"})

        [event] = events(response.text)
        assert event["type"] == "error" and event["code"] == "no_credits"
        assert llm.calls == []

    def test_successful_chat_consumes_one_credit_and_streams(self, user_client, live_db, llm):
        before = credits(user_client, live_db)

        response = user_client.post("/api/chat/stream", json={"message": "Hello"})

        evs = events(response.text)
        assert [e["data"] for e in evs if e["type"] == "token"] == ["Shalom", " friend."]
        assert evs[0]["type"] == "session" and evs[-1]["type"] == "done"
        assert credits(user_client, live_db) == before - 1

    def test_stream_saves_both_messages_to_the_conversation(self, user_client, live_db, llm):
        conv = user_client.portal.call(live_db.create_conversation, USER["id"])

        response = user_client.post("/api/chat/stream", json={"message": "Hello", "conversation_id": str(conv["id"])})

        saved = [e for e in events(response.text) if e["type"] == "message_saved"]
        assert len(saved) == 1
        messages = user_client.portal.call(live_db.get_messages, str(conv["id"]))
        assert [(m["role"], m["content"]) for m in messages] == [("user", "Hello"), ("assistant", "Shalom friend.")]
        assert str(messages[1]["id"]) == str(saved[0]["message_id"])

    def test_stream_failure_refunds_consumed_credit(self, user_client, live_db, llm):
        """If a credit was consumed but the pipeline then fails, refund it and log the error."""
        llm.error = RuntimeError("pipeline exploded")
        before = credits(user_client, live_db)

        response = user_client.post("/api/chat/stream", json={"message": "Hello"})

        assert events(response.text)[-1]["type"] == "error"
        # No raw exception text should leak into the SSE payload.
        assert "pipeline exploded" not in response.text
        assert credits(user_client, live_db) == before
        errors = user_client.portal.call(live_db.admin_list_errors)
        assert [(e["error_type"], e["error_message"]) for e in errors] == [("llm_error", "pipeline exploded")]

    def test_client_disconnect_refunds_credit_when_no_tokens_sent(self, user_client, live_db, llm):
        """CancelledError (client abort / the 90s frontend watchdog) is a
        BaseException, not an Exception, so it needs its own handler to
        refund a consumed credit rather than silently dropping it.
        """
        llm.stream_chunks = ()
        llm.stream_error = asyncio.CancelledError()
        before = credits(user_client, live_db)

        response = user_client.post("/api/chat/stream", json={"message": "Hello"})

        assert response.status_code == 200
        assert '"type": "token"' not in response.text
        assert credits(user_client, live_db) == before

    def test_client_disconnect_does_not_refund_after_partial_response(self, user_client, live_db, llm):
        """If some assistant content was already delivered before the client
        disconnected, the user got value for the credit - don't refund."""
        llm.stream_chunks = ("Shalom",)
        llm.stream_error = asyncio.CancelledError()
        before = credits(user_client, live_db)

        response = user_client.post("/api/chat/stream", json={"message": "Hello"})

        assert '"type": "token"' in response.text
        assert credits(user_client, live_db) == before - 1


class TestCORSMiddleware:
    """Test CORS middleware configuration."""

    def test_cors_preflight_allows_configured_origin(self, client):
        origin = main_module.settings.cors_origins[0]
        response = client.options(
            "/api/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"

    def test_cors_preflight_rejects_unknown_origin(self, client):
        response = client.options(
            "/api/health",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )

        assert "access-control-allow-origin" not in response.headers


class TestAppMetadata:
    """Test app metadata."""

    def test_app_has_description(self):
        assert "progressive Modern Orthodox" in app.description

    def test_app_has_title(self):
        assert app.title.strip()

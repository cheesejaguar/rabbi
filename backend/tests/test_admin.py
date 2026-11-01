"""Tests for admin.py - admin role enforcement and admin API endpoints.

Requests go through the real app with a real signed session cookie, and the
admin endpoints read and write a real PostgreSQL database (see the
``live_db`` fixture in conftest.py).
"""

import pytest
from fastapi.testclient import TestClient

import app.admin as admin_module
import app.main as main_module
from app.auth import create_session_token
from app.main import app


ADMIN_USER = {
    "id": "admin-user-id",
    "email": "cheesejaguar@gmail.com",
    "first_name": "Admin",
    "last_name": "Owner",
}

REGULAR_USER = {
    "id": "regular-user-id",
    "email": "someone@example.com",
    "first_name": "Regular",
    "last_name": "User",
}

OWNER_EMAILS = "cheesejaguar@gmail.com"


def _configure(monkeypatch, database_url, admin_emails=OWNER_EMAILS):
    """Set the real settings the admin router and app read.

    ``app.admin`` and ``app.main`` hold the settings object they imported, so
    set the attributes on those objects directly.
    """
    for settings in {id(s): s for s in (admin_module.settings, main_module.settings)}.values():
        monkeypatch.setattr(settings, "database_url", database_url)
        monkeypatch.setattr(settings, "postgres_url", "")
        monkeypatch.setattr(settings, "pghost", "")
        monkeypatch.setattr(settings, "postgres_host", "")
        monkeypatch.setattr(settings, "admin_emails", admin_emails)


def logged_in(client, user):
    client.cookies.set("session", create_session_token(user))
    return client


@pytest.fixture
def no_db_client(monkeypatch):
    """App client with no database configured."""
    _configure(monkeypatch, "")
    return TestClient(app)


@pytest.fixture
def db_client(live_db, pg_url, monkeypatch):
    """App client backed by the real test database, admin user seeded."""
    _configure(monkeypatch, pg_url)
    with TestClient(app) as client:
        client.portal.call(live_db.upsert_user, ADMIN_USER["id"], ADMIN_USER["email"], "Admin", "Owner")
        client.portal.call(live_db.upsert_user, REGULAR_USER["id"], REGULAR_USER["email"], "Regular", "User")
        yield client, live_db


def _audit_log(client, db):
    return client.portal.call(db.admin_list_audit_log)


class TestConfigAdminEmails:
    """Test the ADMIN_EMAILS setting parsing."""

    def test_default_includes_owner(self):
        from app.config import Settings
        settings = Settings(_env_file=None)
        assert "cheesejaguar@gmail.com" in settings.admin_email_list

    def test_parsing_normalizes_and_strips(self):
        from app.config import Settings
        settings = Settings(_env_file=None, admin_emails=" A@B.com, c@D.com ,,")
        assert settings.admin_email_list == ["a@b.com", "c@d.com"]


class TestRequireAdmin:
    """Test the admin role gate on /api/admin endpoints."""

    def test_unauthenticated_gets_401(self, no_db_client):
        response = no_db_client.get("/api/admin/overview")
        assert response.status_code == 401

    def test_non_admin_gets_403(self, no_db_client):
        response = logged_in(no_db_client, REGULAR_USER).get("/api/admin/overview")
        assert response.status_code == 403

    def test_config_email_admin_passes_role_gate(self, no_db_client):
        # With no database configured the endpoint returns 503 - which
        # proves the 403 role gate was passed for the configured email.
        response = logged_in(no_db_client, ADMIN_USER).get("/api/admin/overview")
        assert response.status_code == 503

    def test_tampered_session_cookie_is_rejected(self, no_db_client):
        token = create_session_token(REGULAR_USER)
        no_db_client.cookies.set("session", token[:-2] + ("AA" if not token.endswith("AA") else "BB"))
        assert no_db_client.get("/api/admin/overview").status_code == 401

    def test_db_flag_admin_passes_role_gate(self, db_client, monkeypatch):
        client, db = db_client
        _configure(monkeypatch, admin_module.settings.database_url, admin_emails="")
        logged_in(client, REGULAR_USER)
        assert client.get("/api/admin/overview").status_code == 403

        client.portal.call(db.admin_set_role, REGULAR_USER["id"], True)
        response = client.get("/api/admin/overview")
        assert response.status_code == 200
        assert response.json()["overview"]["total_users"] == 2

    def test_admin_page_forbidden_for_non_admin(self, no_db_client):
        response = logged_in(no_db_client, REGULAR_USER).get("/admin")
        assert response.status_code == 403

    def test_admin_page_authorized_and_noindex(self, no_db_client):
        response = logged_in(no_db_client, ADMIN_USER).get("/admin")
        assert response.status_code == 200
        assert 'name="robots" content="noindex, nofollow"' in response.text
        assert 'id="tabs"' in response.text


class TestAdminEndpoints:
    """Test admin endpoint behavior with an authenticated admin."""

    def test_overview(self, db_client):
        client, db = db_client
        conv = client.portal.call(db.create_conversation, REGULAR_USER["id"], "Q")
        client.portal.call(db.add_message, conv["id"], "user", "Hello")
        response = logged_in(client, ADMIN_USER).get("/api/admin/overview")
        assert response.status_code == 200
        overview = response.json()["overview"]
        assert overview["total_users"] == 2
        assert overview["total_conversations"] == 1
        assert overview["total_messages"] == 1
        assert overview["active_users_7d"] == 1
        assert overview["revenue_cents_total"] == 0

    def test_list_users_with_search(self, db_client):
        client, _ = db_client
        response = logged_in(client, ADMIN_USER).get("/api/admin/users?search=someone@")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert [u["id"] for u in data["users"]] == [REGULAR_USER["id"]]
        assert data["users"][0]["is_admin"] is False

    def test_adjust_credits_success_and_audited(self, db_client):
        client, db = db_client
        before = client.portal.call(db.get_user_credits, REGULAR_USER["id"])
        response = logged_in(client, ADMIN_USER).post(
            f"/api/admin/users/{REGULAR_USER['id']}/credits",
            json={"delta": 10, "reason": "welcome gift"},
        )
        assert response.status_code == 200
        assert response.json() == {"success": True, "credits": before + 10}
        assert client.portal.call(db.get_user_credits, REGULAR_USER["id"]) == before + 10

        [entry] = _audit_log(client, db)
        assert entry["action"] == "adjust_credits"
        assert entry["admin_user_id"] == ADMIN_USER["id"]
        assert entry["target_user_id"] == REGULAR_USER["id"]
        assert entry["details"]["reason"] == "welcome gift"

    def test_adjust_credits_clamps_at_zero(self, db_client):
        client, db = db_client
        response = logged_in(client, ADMIN_USER).post(
            f"/api/admin/users/{REGULAR_USER['id']}/credits",
            json={"delta": -10000, "reason": "abuse"},
        )
        assert response.status_code == 200
        assert response.json()["credits"] == 0
        assert client.portal.call(db.get_user_credits, REGULAR_USER["id"]) == 0

    def test_adjust_credits_zero_delta_rejected(self, db_client):
        client, db = db_client
        response = logged_in(client, ADMIN_USER).post(
            f"/api/admin/users/{REGULAR_USER['id']}/credits",
            json={"delta": 0, "reason": "noop"},
        )
        assert response.status_code == 400
        assert _audit_log(client, db) == []

    def test_adjust_credits_unknown_user_404(self, db_client):
        client, db = db_client
        response = logged_in(client, ADMIN_USER).post(
            "/api/admin/users/missing-id/credits",
            json={"delta": 5, "reason": "grant"},
        )
        assert response.status_code == 404
        assert _audit_log(client, db) == []

    def test_set_role_grants_admin_and_audits(self, db_client):
        client, db = db_client
        response = logged_in(client, ADMIN_USER).post(
            f"/api/admin/users/{REGULAR_USER['id']}/role",
            json={"is_admin": True},
        )
        assert response.status_code == 200
        assert response.json()["user"]["is_admin"] is True
        assert client.portal.call(db.is_user_admin, REGULAR_USER["id"]) is True
        [entry] = _audit_log(client, db)
        assert entry["action"] == "set_role"
        assert entry["target_user_id"] == REGULAR_USER["id"]

    def test_cannot_revoke_own_admin(self, db_client):
        client, db = db_client
        client.portal.call(db.admin_set_role, ADMIN_USER["id"], True)
        response = logged_in(client, ADMIN_USER).post(
            f"/api/admin/users/{ADMIN_USER['id']}/role",
            json={"is_admin": False},
        )
        assert response.status_code == 400
        assert client.portal.call(db.is_user_admin, ADMIN_USER["id"]) is True

    def test_view_conversation_is_audited(self, db_client):
        client, db = db_client
        conv = client.portal.call(db.create_conversation, REGULAR_USER["id"], "Question")
        client.portal.call(db.add_message, conv["id"], "user", "Is this allowed?")
        response = logged_in(client, ADMIN_USER).get(f"/api/admin/conversations/{conv['id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["user_email"] == REGULAR_USER["email"]
        assert [m["content"] for m in data["messages"]] == ["Is this allowed?"]
        [entry] = _audit_log(client, db)
        assert entry["action"] == "view_conversation"
        assert entry["target_user_id"] == REGULAR_USER["id"]

    def test_view_missing_conversation_404_not_audited(self, db_client):
        client, db = db_client
        response = logged_in(client, ADMIN_USER).get("/api/admin/conversations/missing")
        assert response.status_code == 404
        assert _audit_log(client, db) == []

    def test_flagged_queue(self, db_client):
        client, db = db_client
        conv = client.portal.call(db.create_conversation, REGULAR_USER["id"], "Q")
        flagged = client.portal.call(
            db.add_message, conv["id"], "assistant", "Please reach out for help.",
            {"pastoral_mode": "crisis", "requires_human_referral": True})
        # A routing hint alone is not enough to land in the review queue.
        client.portal.call(
            db.add_message, conv["id"], "assistant", "Here is a teaching.",
            {"pastoral_mode": "counseling", "requires_human_referral": True})
        response = logged_in(client, ADMIN_USER).get("/api/admin/flagged")
        assert response.status_code == 200
        rows = response.json()["flagged"]
        assert [r["id"] for r in rows] == [flagged["id"]]
        assert rows[0]["user_email"] == REGULAR_USER["email"]
        assert rows[0]["requires_human_referral"] is True

    def test_analytics_exposes_stats(self, db_client):
        client, db = db_client
        for session in ("s1", "s2", "s1"):
            client.portal.call(db.log_analytics_event, session, "page_view")
        response = logged_in(client, ADMIN_USER).get("/api/admin/analytics")
        assert response.status_code == 200
        sessions = response.json()["sessions"]
        assert sessions["unique_sessions"] == 2
        assert sessions["total_page_views"] == 3

    def test_feedback_type_validated(self, db_client):
        client, _ = db_client
        response = logged_in(client, ADMIN_USER).get("/api/admin/feedback?feedback_type=bogus")
        assert response.status_code == 422


class TestAdminDatabaseHelpers:
    """Test the admin-related database functions against the real database."""

    async def test_upsert_user_promotes_configured_admin_email(self, real_db, monkeypatch):
        from app.config import get_settings
        monkeypatch.setattr(get_settings(), "admin_emails", OWNER_EMAILS)
        result = await real_db.upsert_user("u1", "CheeseJaguar@Gmail.com", "A", "B")
        assert result["is_admin"] is True
        assert await real_db.is_user_admin("u1") is True

    async def test_upsert_user_regular_email_not_promoted(self, real_db, monkeypatch):
        from app.config import get_settings
        monkeypatch.setattr(get_settings(), "admin_emails", OWNER_EMAILS)
        await real_db.upsert_user("u2", "someone@example.com", "A", "B")
        assert await real_db.is_user_admin("u2") is False

    async def test_is_user_admin_missing_user(self, real_db):
        assert await real_db.is_user_admin("missing") is False

    async def test_admin_adjust_credits_returns_balance(self, real_db):
        await real_db.upsert_user("u1", "a@example.com")
        start = await real_db.get_user_credits("u1")
        assert await real_db.admin_adjust_credits("u1", -3) == start - 3
        assert await real_db.get_user_credits("u1") == start - 3

    async def test_admin_adjust_credits_unknown_user(self, real_db):
        assert await real_db.admin_adjust_credits("missing", 5) is None

    async def test_log_admin_action_inserts_row(self, real_db):
        await real_db.upsert_user("u1", "a@example.com")
        await real_db.upsert_user("u2", "b@example.com")
        result = await real_db.log_admin_action("u1", "adjust_credits", "u2", {"delta": 5})
        assert result["action"] == "adjust_credits"
        assert result["details"] == {"delta": 5}
        [entry] = await real_db.admin_list_audit_log()
        assert entry["id"] == result["id"]
        assert entry["admin_email"] == "a@example.com"
        assert entry["target_email"] == "b@example.com"

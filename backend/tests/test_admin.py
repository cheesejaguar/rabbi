"""Tests for admin.py - admin role enforcement and admin API endpoints."""

import sys
import pytest
from unittest.mock import patch, Mock, AsyncMock


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


@pytest.fixture(scope="module")
def admin_client():
    """Create the app with a mocked orchestrator; auth is patched per-test."""
    mock_orchestrator_instance = Mock()
    mock_orchestrator_instance.get_greeting = AsyncMock(return_value="Shalom!")
    mock_orchestrator_instance.ensure_rag = Mock()

    # Clear cached modules so main.py picks up the patched orchestrator.
    # patch.dict snapshots sys.modules and restores the original modules on
    # teardown so other test modules' module-level imports stay consistent.
    with patch.dict(sys.modules, {}):
        mods_to_remove = [k for k in sys.modules if k.startswith('app')]
        for mod in mods_to_remove:
            del sys.modules[mod]

        with patch('app.agents.orchestrator.OpenAI'):
            with patch('app.agents.RabbiOrchestrator', return_value=mock_orchestrator_instance):
                from app.main import app
                from fastapi.testclient import TestClient
                client = TestClient(app)
                yield client


def logged_in_as(user):
    """Patch session extraction (middleware + admin router) to return `user`."""
    return patch.multiple(
        'app.main', get_current_user=Mock(return_value=user),
    ), patch.multiple(
        'app.admin', get_current_user=Mock(return_value=user),
    )


def admin_settings(db_url="postgresql://test", admin_emails=None):
    """Patch the admin router's settings singleton reference."""
    mock = Mock()
    mock.db_url = db_url
    mock.admin_email_list = admin_emails if admin_emails is not None else ["cheesejaguar@gmail.com"]
    return patch('app.admin.settings', mock)


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

    def test_unauthenticated_gets_401(self, admin_client):
        response = admin_client.get("/api/admin/overview")
        assert response.status_code == 401

    def test_non_admin_gets_403(self, admin_client):
        main_patch, admin_patch = logged_in_as(REGULAR_USER)
        with main_patch, admin_patch, admin_settings(db_url=""):
            response = admin_client.get("/api/admin/overview")
        assert response.status_code == 403

    def test_config_email_admin_passes_role_gate(self, admin_client):
        # With no database configured the endpoint returns 503 - which
        # proves the 403 role gate was passed for the configured email.
        main_patch, admin_patch = logged_in_as(ADMIN_USER)
        with main_patch, admin_patch, admin_settings(db_url=""):
            response = admin_client.get("/api/admin/overview")
        assert response.status_code == 503

    def test_db_flag_admin_passes_role_gate(self, admin_client):
        main_patch, admin_patch = logged_in_as(REGULAR_USER)
        with main_patch, admin_patch, admin_settings(admin_emails=[]):
            with patch('app.admin.db.is_user_admin', new_callable=AsyncMock, return_value=True):
                with patch('app.admin.db.admin_get_overview', new_callable=AsyncMock, return_value={"total_users": 1}):
                    response = admin_client.get("/api/admin/overview")
        assert response.status_code == 200
        assert response.json()["overview"]["total_users"] == 1

    def test_admin_page_forbidden_for_non_admin(self, admin_client):
        main_patch, admin_patch = logged_in_as(REGULAR_USER)
        with main_patch, admin_patch, admin_settings(db_url=""):
            response = admin_client.get("/admin")
        assert response.status_code == 403


class TestAdminEndpoints:
    """Test admin endpoint behavior with an authenticated admin."""

    def _as_admin(self):
        return logged_in_as(ADMIN_USER)

    def test_overview(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        overview = {"total_users": 5, "revenue_cents_total": 300}
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_get_overview', new_callable=AsyncMock, return_value=overview):
                response = admin_client.get("/api/admin/overview")
        assert response.status_code == 200
        assert response.json() == {"overview": overview}

    def test_list_users_with_search(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        users = [{"id": "u1", "email": "a@b.com", "credits": 3, "is_admin": False}]
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_list_users', new_callable=AsyncMock, return_value=users) as mock_list:
                with patch('app.admin.db.admin_count_users', new_callable=AsyncMock, return_value=1):
                    response = admin_client.get("/api/admin/users?search=a@b")
        assert response.status_code == 200
        assert response.json() == {"users": users, "total": 1}
        mock_list.assert_awaited_once_with(search="a@b", limit=50, offset=0)

    def test_adjust_credits_success_and_audited(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_adjust_credits', new_callable=AsyncMock, return_value=13) as mock_adjust:
                with patch('app.admin.db.log_admin_action', new_callable=AsyncMock) as mock_log:
                    response = admin_client.post(
                        "/api/admin/users/target-id/credits",
                        json={"delta": 10, "reason": "welcome gift"},
                    )
        assert response.status_code == 200
        assert response.json() == {"success": True, "credits": 13}
        mock_adjust.assert_awaited_once_with("target-id", 10)
        mock_log.assert_awaited_once()
        assert mock_log.await_args.kwargs["action"] == "adjust_credits"
        assert mock_log.await_args.kwargs["target_user_id"] == "target-id"
        assert mock_log.await_args.kwargs["details"]["reason"] == "welcome gift"

    def test_adjust_credits_zero_delta_rejected(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        with main_patch, admin_patch, admin_settings():
            response = admin_client.post(
                "/api/admin/users/target-id/credits",
                json={"delta": 0, "reason": "noop"},
            )
        assert response.status_code == 400

    def test_adjust_credits_unknown_user_404(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_adjust_credits', new_callable=AsyncMock, return_value=None):
                response = admin_client.post(
                    "/api/admin/users/missing-id/credits",
                    json={"delta": 5, "reason": "grant"},
                )
        assert response.status_code == 404

    def test_set_role_grants_admin_and_audits(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        result = {"id": "target-id", "email": "a@b.com", "is_admin": True}
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_set_role', new_callable=AsyncMock, return_value=result) as mock_role:
                with patch('app.admin.db.log_admin_action', new_callable=AsyncMock) as mock_log:
                    response = admin_client.post(
                        "/api/admin/users/target-id/role",
                        json={"is_admin": True},
                    )
        assert response.status_code == 200
        assert response.json()["user"]["is_admin"] is True
        mock_role.assert_awaited_once_with("target-id", True)
        assert mock_log.await_args.kwargs["action"] == "set_role"

    def test_cannot_revoke_own_admin(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        with main_patch, admin_patch, admin_settings():
            response = admin_client.post(
                f"/api/admin/users/{ADMIN_USER['id']}/role",
                json={"is_admin": False},
            )
        assert response.status_code == 400

    def test_view_conversation_is_audited(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        conversation = {
            "id": "conv-1", "user_id": "target-id", "user_email": "a@b.com",
            "title": "Question", "messages": [],
        }
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_get_conversation_with_messages', new_callable=AsyncMock, return_value=conversation):
                with patch('app.admin.db.log_admin_action', new_callable=AsyncMock) as mock_log:
                    response = admin_client.get("/api/admin/conversations/conv-1")
        assert response.status_code == 200
        assert mock_log.await_args.kwargs["action"] == "view_conversation"

    def test_flagged_queue(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        flagged = [{"id": "m1", "requires_human_referral": True, "user_email": "a@b.com"}]
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.admin_list_flagged_messages', new_callable=AsyncMock, return_value=flagged):
                response = admin_client.get("/api/admin/flagged")
        assert response.status_code == 200
        assert response.json() == {"flagged": flagged}

    def test_analytics_exposes_stats(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        with main_patch, admin_patch, admin_settings():
            with patch('app.admin.db.get_session_stats', new_callable=AsyncMock, return_value={"unique_sessions": 4}):
                with patch('app.admin.db.get_referrer_stats', new_callable=AsyncMock, return_value=[]):
                    with patch('app.admin.db.get_device_stats', new_callable=AsyncMock, return_value=[]):
                        with patch('app.admin.db.get_tts_stats', new_callable=AsyncMock, return_value={}):
                            response = admin_client.get("/api/admin/analytics")
        assert response.status_code == 200
        assert response.json()["sessions"]["unique_sessions"] == 4

    def test_feedback_type_validated(self, admin_client):
        main_patch, admin_patch = self._as_admin()
        with main_patch, admin_patch, admin_settings():
            response = admin_client.get("/api/admin/feedback?feedback_type=bogus")
        assert response.status_code == 422


class TestAdminDatabaseHelpers:
    """Test the admin-related database functions with a mocked connection."""

    @pytest.fixture
    def mock_connection(self):
        return AsyncMock()

    def _patch_conn(self, mock_connection):
        ctx = patch('app.database.get_connection')
        mock_ctx = ctx.start()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.return_value.__aexit__ = AsyncMock()
        return ctx

    @pytest.mark.asyncio
    async def test_upsert_user_promotes_configured_admin_email(self, mock_connection):
        mock_connection.fetchrow = AsyncMock(return_value={
            "id": "u1", "email": "cheesejaguar@gmail.com", "is_admin": True,
        })
        ctx = self._patch_conn(mock_connection)
        try:
            with patch('app.database.get_settings') as mock_settings:
                mock_settings.return_value.admin_email_list = ["cheesejaguar@gmail.com"]
                from app.database import upsert_user
                result = await upsert_user("u1", "CheeseJaguar@Gmail.com", "A", "B")
        finally:
            ctx.stop()
        # The is_admin insert parameter (last positional arg) must be True
        assert mock_connection.fetchrow.call_args[0][-1] is True
        assert result["is_admin"] is True

    @pytest.mark.asyncio
    async def test_upsert_user_regular_email_not_promoted(self, mock_connection):
        mock_connection.fetchrow = AsyncMock(return_value={
            "id": "u2", "email": "someone@example.com", "is_admin": False,
        })
        ctx = self._patch_conn(mock_connection)
        try:
            with patch('app.database.get_settings') as mock_settings:
                mock_settings.return_value.admin_email_list = ["cheesejaguar@gmail.com"]
                from app.database import upsert_user
                await upsert_user("u2", "someone@example.com", "A", "B")
        finally:
            ctx.stop()
        assert mock_connection.fetchrow.call_args[0][-1] is False

    @pytest.mark.asyncio
    async def test_is_user_admin_true(self, mock_connection):
        mock_connection.fetchrow = AsyncMock(return_value={"is_admin": True})
        ctx = self._patch_conn(mock_connection)
        try:
            from app.database import is_user_admin
            assert await is_user_admin("u1") is True
        finally:
            ctx.stop()

    @pytest.mark.asyncio
    async def test_is_user_admin_missing_user(self, mock_connection):
        mock_connection.fetchrow = AsyncMock(return_value=None)
        ctx = self._patch_conn(mock_connection)
        try:
            from app.database import is_user_admin
            assert await is_user_admin("missing") is False
        finally:
            ctx.stop()

    @pytest.mark.asyncio
    async def test_admin_adjust_credits_returns_balance(self, mock_connection):
        mock_connection.fetchrow = AsyncMock(return_value={"credits": 7})
        ctx = self._patch_conn(mock_connection)
        try:
            from app.database import admin_adjust_credits
            assert await admin_adjust_credits("u1", -3) == 7
        finally:
            ctx.stop()

    @pytest.mark.asyncio
    async def test_log_admin_action_inserts_row(self, mock_connection):
        row = {"id": "a1", "admin_user_id": "u1", "action": "adjust_credits",
               "target_user_id": "u2", "details": {"delta": 5}, "created_at": "now"}
        mock_connection.fetchrow = AsyncMock(return_value=row)
        ctx = self._patch_conn(mock_connection)
        try:
            from app.database import log_admin_action
            result = await log_admin_action("u1", "adjust_credits", "u2", {"delta": 5})
        finally:
            ctx.stop()
        assert result["action"] == "adjust_credits"
        mock_connection.fetchrow.assert_awaited_once()

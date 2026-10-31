"""Tests for the public web surface: landing page, robots.txt, sitemap,
and the Shabbat/yom tov calendar-status endpoint."""

import json
from pathlib import Path
import sys
import pytest
from unittest.mock import patch, Mock, AsyncMock


AUTH_USER = {
    "id": "user-1",
    "email": "someone@example.com",
    "first_name": "Some",
    "last_name": "One",
}


@pytest.fixture(scope="module")
def public_client():
    """Create the app with a mocked orchestrator; no auth patched by default."""
    mock_orchestrator_instance = Mock()
    mock_orchestrator_instance.get_greeting = AsyncMock(return_value="Shalom!")
    mock_orchestrator_instance.ensure_rag = Mock()

    # patch.dict snapshots sys.modules and restores originals on teardown
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


class TestLandingPage:
    """Test the public landing page and app routing at /."""

    def test_unauthenticated_visitor_gets_landing_page(self, public_client):
        response = public_client.get("/")
        assert response.status_code == 200
        assert "Thoughtful Jewish guidance, grounded in sources." in response.text
        assert "guidance, not psak" in response.text.lower()
        assert "How can I make Shabbat meaningful if I’m just beginning?" in response.text
        assert "Static example" in response.text
        assert '"price": "0"' not in response.text
        assert 'href="/privacy"' in response.text

    def test_authenticated_user_gets_app(self, public_client):
        with patch('app.main.get_current_user', return_value=AUTH_USER):
            response = public_client.get("/")
        assert response.status_code == 200
        # The app shell, not the marketing page
        assert 'id="welcomeScreen"' in response.text

    def test_robots_txt_public(self, public_client):
        response = public_client.get("/robots.txt")
        assert response.status_code == 200
        assert "Disallow: /api/" in response.text
        assert "Disallow: /admin" in response.text
        assert "Sitemap:" in response.text

    def test_sitemap_xml_public(self, public_client):
        response = public_client.get("/sitemap.xml")
        assert response.status_code == 200
        assert "<urlset" in response.text
        assert "<loc>https://rebbe.dev/privacy</loc>" in response.text


class TestPrivacyPolicy:
    """Test that the policy remains public, substantive, and deployable."""

    def test_anonymous_privacy_policy_is_direct_and_crawlable(self, public_client):
        response = public_client.get("/privacy")

        assert response.status_code == 200
        assert response.history == []
        assert response.headers["content-type"].startswith("text/html")
        assert "Privacy Policy | rebbe.dev" in response.text
        assert '<link rel="canonical" href="https://rebbe.dev/privacy">' in response.text
        assert "October 31, 2026" in response.text
        assert "Information we process" in response.text
        assert "AI, safety review, and text-to-speech processing" in response.text
        assert "Retention and deletion" in response.text
        assert "WorkOS" in response.text
        assert "Stripe" in response.text
        assert "ElevenLabs" in response.text
        assert "deleted automatically" in response.text
        assert "Anthropic" in response.text

    def test_authenticated_visitor_still_gets_policy(self, public_client):
        with patch('app.main.get_current_user', return_value=AUTH_USER):
            response = public_client.get("/privacy")

        assert response.status_code == 200
        assert "Privacy Policy | rebbe.dev" in response.text
        assert 'id="welcomeScreen"' not in response.text

    def test_trailing_slash_canonicalizes_without_auth_redirect(self, public_client):
        response = public_client.get("/privacy/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"].endswith("/privacy")

    def test_vercel_privacy_route_precedes_frontend_catchall(self):
        root = Path(__file__).resolve().parents[2]
        routes = json.loads((root / "vercel.json").read_text())["routes"]
        privacy_index = next(
            index for index, route in enumerate(routes) if route["src"] == "/privacy/?"
        )
        catchall_index = next(
            index for index, route in enumerate(routes) if route["src"] == "/(.*)"
        )

        assert routes[privacy_index]["dest"] == "/api/index.py"
        assert privacy_index < catchall_index


class TestCalendarStatusEndpoint:
    """Test GET /api/calendar-status (public)."""

    def test_shabbat_from_client_time(self, public_client):
        # Saturday midday, client-local
        response = public_client.get("/api/calendar-status?client_time=2026-07-04T12:00:00")
        assert response.status_code == 200
        data = response.json()
        assert data["is_shabbat"] is True
        assert "Shabbat" in data["message"]

    def test_ordinary_weekday(self, public_client):
        response = public_client.get("/api/calendar-status?client_time=2026-07-01T12:00:00")
        assert response.status_code == 200
        data = response.json()
        assert data["is_shabbat"] is False
        assert data["message"] is None

    def test_invalid_client_time_falls_back_gracefully(self, public_client):
        response = public_client.get("/api/calendar-status?client_time=not-a-date")
        assert response.status_code == 200
        # Falls back to server time; shape must still be intact
        data = response.json()
        assert "is_shabbat" in data
        assert "message" in data

    def test_yom_tov_reported(self, public_client):
        # Rosh Hashana 5787: September 12 2026
        response = public_client.get("/api/calendar-status?client_time=2026-09-12T10:00:00")
        data = response.json()
        assert data["is_yom_tov"] is True
        assert data["holiday_name"] == "Rosh Hashana"


class TestDvarTorahEndpoint:
    """Test GET /api/dvar-torah uses the client's local date."""

    def test_client_date_selects_parsha_week(self, public_client):
        # 03:42 UTC Friday is still Thursday evening in the US.
        from datetime import date, datetime, timezone
        utc_now = datetime(2026, 10, 30, 3, 42, tzinfo=timezone.utc)
        generate = AsyncMock(return_value=None)
        with patch('app.main.get_or_generate_dvar_torah', generate), \
                patch('app.dvar_torah.datetime') as mock_dt:
            mock_dt.now.return_value = utc_now
            response = public_client.get("/api/dvar-torah?client_date=2026-10-29")
        assert response.status_code == 200
        assert generate.call_args.args[2] == date(2026, 10, 29)


class TestTermsOfService:
    """The public Terms of Service page (ages 13+, not for emergencies)."""

    def test_terms_page_is_public_and_states_core_terms(self, public_client):
        client = public_client
        response = client.get("/terms")
        assert response.status_code == 200
        assert "Terms of Service | rebbe.dev" in response.text
        assert "at least 13 years old" in response.text
        assert "Not for emergencies" in response.text
        assert "guidance, not psak" in response.text.lower()
        assert client.head("/terms").status_code == 200

    def test_terms_route_precedes_vercel_catchall(self):
        import json
        from pathlib import Path

        routes = json.loads((Path(__file__).parents[2] / "vercel.json").read_text())["routes"]
        srcs = [r["src"] for r in routes]
        assert srcs.index("/terms/?") < srcs.index("/(.*)")
        assert srcs.index("/c/(.*)") < srcs.index("/(.*)")


class TestDvarTorahAudio:
    """Read-aloud recording endpoint: generated once, then served from cache."""

    DVAR = {"parsha_name": "Vayeira", "parsha_name_hebrew": "וירא", "hebrew_year": 5787,
            "content": "On שבת (Shabbat) we learn hospitality."}

    def test_ready_audio_is_served_with_cache_headers_and_etag(self, public_client):
        with patch("app.main.get_or_generate_dvar_torah", AsyncMock(return_value=self.DVAR)), \
             patch("app.main.dvar_audio.get_or_create_audio", AsyncMock(return_value=("ready", b"MP3DATA"))):
            r = public_client.get("/api/dvar-torah/audio?client_date=2026-10-31")
            assert r.status_code == 200 and r.content == b"MP3DATA"
            assert r.headers["content-type"] == "audio/mpeg"
            assert "max-age=86400" in r.headers["cache-control"]
            again = public_client.get("/api/dvar-torah/audio", headers={"If-None-Match": r.headers["etag"]})
            assert again.status_code == 304

    def test_generating_returns_202_with_retry(self, public_client):
        with patch("app.main.get_or_generate_dvar_torah", AsyncMock(return_value=self.DVAR)), \
             patch("app.main.dvar_audio.get_or_create_audio", AsyncMock(return_value=("generating", None))):
            r = public_client.get("/api/dvar-torah/audio")
            assert r.status_code == 202 and r.json()["status"] == "generating"
            assert r.headers["retry-after"] == "4"

    def test_unavailable_and_holiday_weeks(self, public_client):
        with patch("app.main.get_or_generate_dvar_torah", AsyncMock(return_value=self.DVAR)), \
             patch("app.main.dvar_audio.get_or_create_audio", AsyncMock(return_value=("unavailable", None))):
            assert public_client.get("/api/dvar-torah/audio").status_code == 503
        with patch("app.main.get_or_generate_dvar_torah", AsyncMock(return_value=None)):
            assert public_client.get("/api/dvar-torah/audio").status_code == 404

    def test_regenerate_requires_admin(self, public_client):
        assert public_client.post("/api/admin/dvar-torah/regenerate").status_code in (401, 403)

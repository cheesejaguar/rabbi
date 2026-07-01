"""Tests for the public web surface: landing page, robots.txt, sitemap,
and the Shabbat/yom tov calendar-status endpoint."""

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
        assert "Torah wisdom and guidance" in response.text
        assert "guidance, not psak" in response.text.lower()

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

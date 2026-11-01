"""Tests for the public web surface: landing page, robots.txt, sitemap,
and the Shabbat/yom tov calendar-status endpoint."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app import dvar_audio, dvar_torah
from app.auth import create_session_token
from app.config import get_settings
from app.main import app


AUTH_USER = {
    "id": "user-1",
    "email": "someone@example.com",
    "first_name": "Some",
    "last_name": "One",
}


@pytest.fixture
def public_client(monkeypatch):
    """The real app with no database configured and no session cookie."""
    _set_db_url(monkeypatch, "")
    return TestClient(app)


def _set_db_url(monkeypatch, url):
    for settings in {id(s): s for s in (get_settings(), main_module.settings)}.values():
        monkeypatch.setattr(settings, "database_url", url)
        monkeypatch.setattr(settings, "postgres_url", "")
        monkeypatch.setattr(settings, "pghost", "")
        monkeypatch.setattr(settings, "postgres_host", "")


def _logged_in(client):
    client.cookies.set("session", create_session_token(AUTH_USER))
    return client


def _freeze_utc_now(monkeypatch, frozen):
    """Pin the server clock the d'var Torah week is resolved against."""
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

    monkeypatch.setattr(dvar_torah, "datetime", FrozenDatetime)


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
        response = _logged_in(public_client).get("/")
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
        response = _logged_in(public_client).get("/privacy")

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

    def test_client_date_selects_parsha_week(self, live_db, pg_url, monkeypatch):
        # 03:42 UTC Friday is still Thursday evening in the US: the client's
        # Thursday date keeps last Shabbat's parsha (Lech Lecha) rather than
        # moving on to the coming one (Vayeira).
        _set_db_url(monkeypatch, pg_url)
        _freeze_utc_now(monkeypatch, datetime(2026, 10, 30, 3, 42, tzinfo=timezone.utc))
        with TestClient(app) as client:
            client.portal.call(live_db.save_dvar_torah, "Lech Lecha", "לך לך", 5787, "Go forth.")
            client.portal.call(live_db.save_dvar_torah, "Vayeira", "וירא", 5787, "Hospitality.")
            thursday = client.get("/api/dvar-torah?client_date=2026-10-29").json()
            friday = client.get("/api/dvar-torah?client_date=2026-10-30").json()
            out_of_range = client.get("/api/dvar-torah?client_date=2026-10-20").json()
        assert (thursday["parsha_name"], thursday["content"]) == ("Lech Lecha", "Go forth.")
        assert thursday["is_holiday_week"] is False
        assert friday["parsha_name"] == "Vayeira"
        # A client date more than a day off is ignored in favour of server time.
        assert out_of_range["parsha_name"] == "Vayeira"


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

    CONTENT = "On שבת (Shabbat) we learn hospitality."

    @pytest.fixture
    def audio_client(self, live_db, pg_url, monkeypatch):
        """Vayeira week, with this week's d'var Torah already written."""
        _set_db_url(monkeypatch, pg_url)
        monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "")
        _freeze_utc_now(monkeypatch, datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc))
        with TestClient(app) as client:
            client.portal.call(live_db.save_dvar_torah, "Vayeira", "וירא", 5787, self.CONTENT)
            client.db = live_db
            yield client

    def _key(self):
        return dvar_audio.audio_key(dvar_audio.speech_text(self.CONTENT))

    def test_ready_audio_is_served_with_cache_headers_and_etag(self, audio_client):
        db = audio_client.db
        assert audio_client.portal.call(db.claim_dvar_audio, self._key(), "Vayeira", 5787, 300)
        audio_client.portal.call(db.complete_dvar_audio, self._key(), b"MP3DATA", dvar_audio.MIME, 10)

        r = audio_client.get("/api/dvar-torah/audio?client_date=2026-10-31")
        assert r.status_code == 200 and r.content == b"MP3DATA"
        assert r.headers["content-type"] == "audio/mpeg"
        assert "max-age=86400" in r.headers["cache-control"]
        again = audio_client.get("/api/dvar-torah/audio", headers={"If-None-Match": r.headers["etag"]})
        assert again.status_code == 304

    def test_generating_returns_202_with_retry(self, audio_client, monkeypatch):
        # Another request holds the generation claim and has not finished yet.
        monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "test-key-not-used")
        assert audio_client.portal.call(audio_client.db.claim_dvar_audio, self._key(), "Vayeira", 5787, 300)

        r = audio_client.get("/api/dvar-torah/audio")
        assert r.status_code == 202 and r.json()["status"] == "generating"
        assert r.headers["retry-after"] == "4"

    def test_unavailable_without_tts_key(self, audio_client):
        r = audio_client.get("/api/dvar-torah/audio")
        assert r.status_code == 503
        assert r.json()["status"] == "unavailable"

    def test_holiday_week_has_no_audio(self, public_client, monkeypatch):
        # Shabbat chol hamoed Sukkot: no weekly parsha, so nothing to read.
        _freeze_utc_now(monkeypatch, datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
        assert public_client.get("/api/dvar-torah/audio").status_code == 404

    def test_regenerate_requires_admin(self, public_client):
        assert public_client.post("/api/admin/dvar-torah/regenerate").status_code == 401
        assert _logged_in(public_client).post("/api/admin/dvar-torah/regenerate").status_code == 403

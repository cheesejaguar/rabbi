"""Tests for the cached d'var Torah read-aloud audio (app/dvar_audio.py)."""

import json

import httpx
import pytest

from app import dvar_audio


def test_speech_text_reads_each_hebrew_term_once():
    text = ('On שבת (Shabbat) we recall חסד (chesed, loving-kindness) and the רמב"ם (Rambam).\n\n'
            '"וירא אליו ה\'" ("The Lord appeared to him").')
    spoken = dvar_audio.speech_text(text)
    assert spoken.startswith("On Shabbat we recall chesed, loving-kindness and the Rambam.")
    assert "שבת" not in spoken and "חסד" not in spoken
    # A quoted verse with no transliteration is kept, to be read in Hebrew.
    assert "וירא אליו" in spoken


def test_audio_key_changes_with_text_and_voice():
    a = dvar_audio.audio_key("one")
    assert a == dvar_audio.audio_key("one") and a != dvar_audio.audio_key("two")


class FakeElevenLabs:
    """Stands in for the ElevenLabs HTTP API; records each request it receives."""

    def __init__(self, status=200, body=b"MP3"):
        self.status, self.body, self.requests = status, body, []

    def install(self, monkeypatch):
        real_client = httpx.AsyncClient

        def client(*args, **kwargs):
            return real_client(*args, transport=httpx.MockTransport(self._handle), **kwargs)

        monkeypatch.setattr(dvar_audio.httpx, "AsyncClient", client)
        return self

    def _handle(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, content=self.body)


@pytest.fixture
def elevenlabs(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "k")
    monkeypatch.setattr(get_settings(), "elevenlabs_voice_id", "voice")
    return FakeElevenLabs().install(monkeypatch)


@pytest.fixture
def no_db(monkeypatch):
    from app.config import get_settings

    for field in ("database_url", "postgres_url", "pghost", "postgres_host"):
        monkeypatch.setattr(get_settings(), field, "")
    dvar_audio._memory_cache.clear()
    yield
    dvar_audio._memory_cache.clear()


async def test_synthesis_request_sent_to_elevenlabs(elevenlabs, no_db):
    assert await dvar_audio.get_or_create_audio("On שבת (Shabbat) we rest.", "Vayeira", 5787) == ("ready", b"MP3")
    [req] = elevenlabs.requests
    assert req.method == "POST"
    assert req.url.path == "/v1/text-to-speech/voice"
    assert req.url.params["output_format"] == dvar_audio.OUTPUT_FORMAT
    assert req.headers["xi-api-key"] == "k"
    assert json.loads(req.content) == {"text": "On Shabbat we rest.", "model_id": dvar_audio.TTS_MODEL}


async def test_without_db_generates_once_and_reuses(elevenlabs, no_db):
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"MP3")
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"MP3")
    assert len(elevenlabs.requests) == 1


async def test_db_first_listener_generates_and_stores(elevenlabs, real_db):
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"MP3")
    row = await real_db.get_dvar_audio(dvar_audio.audio_key("Shalom"))
    assert bytes(row["audio"]) == b"MP3" and row["mime"] == "audio/mpeg"


async def test_db_cached_audio_is_served_without_elevenlabs(elevenlabs, real_db):
    key = dvar_audio.audio_key("Shalom")
    await real_db.claim_dvar_audio(key, "Vayeira", 5787, 300)
    await real_db.complete_dvar_audio(key, b"CACHED", "audio/mpeg", 6)
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"CACHED")
    assert elevenlabs.requests == []


async def test_db_concurrent_listener_waits_instead_of_paying_again(elevenlabs, real_db):
    # Another instance holds a fresh claim and has not finished yet.
    await real_db.claim_dvar_audio(dvar_audio.audio_key("Shalom"), "Vayeira", 5787, 300)
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("generating", None)
    assert elevenlabs.requests == []


async def test_db_failed_generation_releases_claim(elevenlabs, real_db):
    elevenlabs.status = 500
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("unavailable", None)
    assert await real_db.get_dvar_audio(dvar_audio.audio_key("Shalom")) is None
    # The released claim lets the next listener retry.
    elevenlabs.status = 200
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"MP3")


async def test_empty_elevenlabs_body_is_unavailable(elevenlabs, real_db):
    elevenlabs.body = b""
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("unavailable", None)


async def test_no_elevenlabs_key_is_unavailable(elevenlabs, no_db, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "")
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("unavailable", None)
    assert elevenlabs.requests == []

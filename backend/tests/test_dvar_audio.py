"""Tests for the cached d'var Torah read-aloud audio (app/dvar_audio.py)."""

from unittest.mock import AsyncMock, patch

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


@pytest.fixture
def settings():
    with patch.object(dvar_audio, "get_settings") as gs:
        s = gs.return_value
        s.elevenlabs_api_key = "k"
        s.elevenlabs_voice_id = "voice"
        yield s


async def test_without_db_generates_once_and_reuses(settings):
    settings.db_url = ""
    dvar_audio._memory_cache.clear()
    synth = AsyncMock(return_value=b"MP3")
    with patch.object(dvar_audio, "_synthesize", synth):
        assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"MP3")
        assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"MP3")
    synth.assert_awaited_once()


async def test_db_cached_audio_is_served_without_elevenlabs(settings):
    settings.db_url = "postgres://x"
    synth = AsyncMock()
    with patch.object(dvar_audio.db, "get_dvar_audio", AsyncMock(return_value={"audio": b"CACHED"})), \
         patch.object(dvar_audio, "_synthesize", synth):
        assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"CACHED")
    synth.assert_not_awaited()


async def test_db_first_listener_generates_and_stores(settings):
    settings.db_url = "postgres://x"
    complete = AsyncMock()
    with patch.object(dvar_audio.db, "get_dvar_audio", AsyncMock(return_value=None)), \
         patch.object(dvar_audio.db, "claim_dvar_audio", AsyncMock(return_value=True)), \
         patch.object(dvar_audio.db, "complete_dvar_audio", complete), \
         patch.object(dvar_audio, "_synthesize", AsyncMock(return_value=b"NEW")):
        assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("ready", b"NEW")
    complete.assert_awaited_once()


async def test_db_concurrent_listener_waits_instead_of_paying_again(settings):
    settings.db_url = "postgres://x"
    synth = AsyncMock()
    with patch.object(dvar_audio.db, "get_dvar_audio", AsyncMock(return_value={"audio": None})), \
         patch.object(dvar_audio.db, "claim_dvar_audio", AsyncMock(return_value=False)), \
         patch.object(dvar_audio, "_synthesize", synth):
        assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("generating", None)
    synth.assert_not_awaited()


async def test_db_failed_generation_releases_claim(settings):
    settings.db_url = "postgres://x"
    release = AsyncMock()
    with patch.object(dvar_audio.db, "get_dvar_audio", AsyncMock(return_value=None)), \
         patch.object(dvar_audio.db, "claim_dvar_audio", AsyncMock(return_value=True)), \
         patch.object(dvar_audio.db, "release_dvar_audio_claim", release), \
         patch.object(dvar_audio, "_synthesize", AsyncMock(side_effect=RuntimeError("boom"))):
        assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("unavailable", None)
    release.assert_awaited_once()


async def test_no_elevenlabs_key_is_unavailable(settings):
    settings.db_url = ""
    settings.elevenlabs_api_key = ""
    dvar_audio._memory_cache.clear()
    assert await dvar_audio.get_or_create_audio("Shalom", "Vayeira", 5787) == ("unavailable", None)

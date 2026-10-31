"""Read-aloud audio for the weekly d'var Torah, generated once and cached.

The d'var Torah text is generated once per parsha and stored, so its audio is
too: the first listener triggers one ElevenLabs request, the MP3 is stored in
Postgres keyed by a hash of the exact spoken text (plus voice and model), and
every later play is served from the database and the CDN. A new or
regenerated d'var Torah has a new hash and gets fresh audio.

Generation is claimed with an insert-if-absent row, so concurrent first
listeners never pay for duplicate generations; latecomers get ``202`` and
retry. A claim older than ``STALE_CLAIM_SECONDS`` (a crashed generation) is
taken over.
"""

import hashlib
import logging
import re
from typing import Optional

import httpx

from . import database as db
from .config import get_settings

logger = logging.getLogger(__name__)

TTS_MODEL = "eleven_v3"
OUTPUT_FORMAT = "mp3_44100_64"  # ~0.5 MB per minute; a 5-minute reading stays well under 4 MB
MIME = "audio/mpeg"
STALE_CLAIM_SECONDS = 300
MAX_SPEECH_CHARS = 6000

# A Hebrew term of up to five words followed by "(transliteration[, gloss])".
# A longer Hebrew run (a quoted verse) or a parenthesis that opens with a quote
# mark (a translation) is not a term pair and is left alone.
_HEB = "֐-׿יִ-ﭏ"
_HEB_WORD = "[" + _HEB + "][" + _HEB + "\"'׳״\\-־]*"
_HEBREW_TERM_WITH_TRANSLIT = re.compile(
    "(?<![" + _HEB + "\"])" + _HEB_WORD + "(?: " + _HEB_WORD + "){0,4}"
    + "\\s*\\((?![\"“'])([^()]*[A-Za-z][^()]*)\\)"
)

# In-process fallback when no database is configured (local development).
_memory_cache: dict[str, bytes] = {}


def speech_text(content: str) -> str:
    """Text to read aloud.

    Written answers show "שבת (Shabbat)" so readers see the Hebrew letters; a
    listener would hear the word twice. For speech, each Hebrew-term-plus-
    transliteration pair is read once, as the transliteration (and gloss).
    Hebrew that stands alone, such as a quoted verse, is kept and read in Hebrew.
    """
    text = _HEBREW_TERM_WITH_TRANSLIT.sub(lambda m: m.group(1).strip(), content or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_SPEECH_CHARS]


def audio_key(spoken: str) -> str:
    s = get_settings()
    return hashlib.sha256(f"{s.elevenlabs_voice_id}|{TTS_MODEL}|{OUTPUT_FORMAT}|{spoken}".encode()).hexdigest()


async def _synthesize(spoken: str) -> bytes:
    s = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        r = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{s.elevenlabs_voice_id}",
            params={"output_format": OUTPUT_FORMAT},
            headers={"xi-api-key": s.elevenlabs_api_key, "Content-Type": "application/json"},
            json={"text": spoken, "model_id": TTS_MODEL},
        )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs returned {r.status_code}")
        if not r.content:
            raise RuntimeError("ElevenLabs returned no audio")
        return r.content


async def get_or_create_audio(content: str, parsha_name: str, hebrew_year: int) -> tuple[str, Optional[bytes]]:
    """Return ``(status, audio)`` with status ``ready``, ``generating`` or ``unavailable``."""
    s = get_settings()
    spoken = speech_text(content)
    if not spoken:
        return "unavailable", None
    key = audio_key(spoken)

    if not s.db_url:
        if key not in _memory_cache:
            if not s.elevenlabs_api_key:
                return "unavailable", None
            _memory_cache[key] = await _synthesize(spoken)
        return "ready", _memory_cache[key]

    row = await db.get_dvar_audio(key)
    if row and row.get("audio"):
        return "ready", bytes(row["audio"])
    if not s.elevenlabs_api_key:
        return "unavailable", None
    if not await db.claim_dvar_audio(key, parsha_name, hebrew_year, STALE_CLAIM_SECONDS):
        return "generating", None
    try:
        audio = await _synthesize(spoken)
    except Exception as e:
        logger.error("D'var Torah audio generation failed: %s", e)
        await db.release_dvar_audio_claim(key)
        return "unavailable", None
    await db.complete_dvar_audio(key, audio, MIME, len(spoken))
    logger.info("Generated d'var Torah audio for %s %s (%d chars, %d bytes)",
                parsha_name, hebrew_year, len(spoken), len(audio))
    return "ready", audio


def etag_for(audio: bytes) -> str:
    return '"' + hashlib.sha256(audio).hexdigest()[:32] + '"'

"""Caching, claim and admin-regenerate behaviour of the weekly d'var Torah.

Runs against the real test PostgreSQL (``real_db``); only the LLM provider
client is faked.
"""

from datetime import date
from types import SimpleNamespace as NS

import pytest

from app import dvar_torah

SHABBAT = date(2026, 10, 31)  # Shabbat Vayeira 5787
TEXT = "On שבת (Shabbat) we learn."


class FakeLLM:
    """OpenAI-compatible client double: records requests, returns canned text."""

    def __init__(self, text=TEXT, error=None):
        self.text, self.error, self.calls = text, error, []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return NS(choices=[NS(message=NS(content=self.text))],
                  usage=NS(prompt_tokens=1000, completion_tokens=500))


async def _row(db):
    return await db.get_dvar_torah("Vayeira", 5787)


async def test_generates_once_then_serves_from_cache(real_db):
    llm = FakeLLM()
    first = await dvar_torah.get_or_generate_dvar_torah(llm, "m", SHABBAT)
    second = await dvar_torah.get_or_generate_dvar_torah(llm, "m", SHABBAT)

    assert first == second == {"parsha_name": "Vayeira", "parsha_name_hebrew": first["parsha_name_hebrew"],
                               "hebrew_year": 5787, "content": TEXT}
    assert len(llm.calls) == 1
    request = llm.calls[0]
    assert request["model"] == "m"
    assert "Parashat Vayeira" in request["messages"][1]["content"]
    row = await _row(real_db)
    assert row["content"] == TEXT and row["generating"] is False
    assert row["metadata"]["input_tokens"] == 1000 and row["metadata"]["output_tokens"] == 500


async def test_stuck_placeholder_never_hangs_the_request(real_db):
    # Another instance holds a fresh slot and never finishes: the wait is bounded.
    await real_db.claim_dvar_torah_generation("Vayeira", "וירא", 5787)
    llm = FakeLLM()
    result = await dvar_torah.get_or_generate_dvar_torah(llm, "m", SHABBAT, wait_seconds=0.05, poll_seconds=0.01)
    assert result is None
    assert llm.calls == []
    assert (await _row(real_db))["generating"] is True


async def test_dead_placeholder_is_taken_over_and_completed(real_db):
    await real_db.claim_dvar_torah_generation("Vayeira", "וירא", 5787)
    # The instance that claimed it died long ago.
    async with real_db.get_connection() as conn:
        await conn.execute("UPDATE dvar_torah SET created_at = NOW() - INTERVAL '1 hour'")
    llm = FakeLLM()
    result = await dvar_torah.get_or_generate_dvar_torah(llm, "m", SHABBAT, wait_seconds=5, poll_seconds=0.01)
    assert result["content"] == TEXT
    assert len(llm.calls) == 1
    row = await _row(real_db)
    assert row["content"] == TEXT and row["generating"] is False


async def test_failed_generation_releases_the_slot(real_db):
    result = await dvar_torah.get_or_generate_dvar_torah(FakeLLM(error=RuntimeError("gateway down")), "m", SHABBAT)
    assert result is None
    assert await _row(real_db) is None
    # The next request can claim and generate.
    assert (await dvar_torah.get_or_generate_dvar_torah(FakeLLM(), "m", SHABBAT))["content"] == TEXT


async def test_empty_model_output_is_treated_as_failure(real_db):
    assert await dvar_torah.get_or_generate_dvar_torah(FakeLLM(text="   "), "m", SHABBAT) is None
    assert await _row(real_db) is None


async def test_regenerate_replaces_text_and_drops_old_audio(real_db):
    await dvar_torah.get_or_generate_dvar_torah(FakeLLM(text="Old text."), "m", SHABBAT)
    assert await real_db.claim_dvar_audio("k", "Vayeira", 5787, 600)
    await real_db.complete_dvar_audio("k", b"MP3", "audio/mpeg", 9)

    result = await dvar_torah.regenerate_dvar_torah(FakeLLM(), "m", SHABBAT)

    assert result["parsha_name"] == "Vayeira" and result["content"] == TEXT
    assert (await _row(real_db))["content"] == TEXT
    assert await real_db.get_dvar_audio("k") is None


async def test_failed_regenerate_leaves_the_cache_alone(real_db):
    await dvar_torah.get_or_generate_dvar_torah(FakeLLM(text="Old text."), "m", SHABBAT)
    with pytest.raises(RuntimeError):
        await dvar_torah.regenerate_dvar_torah(FakeLLM(error=RuntimeError("gateway down")), "m", SHABBAT)
    row = await _row(real_db)
    assert row["content"] == "Old text." and row["generating"] is False

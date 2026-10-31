"""Caching, claim and admin-regenerate behaviour of the weekly d'var Torah."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app import dvar_torah

SHABBAT = date(2026, 10, 31)
METRICS = {"latency_ms": 5, "model": "m"}


def row(content="", generating=False):
    return {"parsha_name": "Vayeira", "parsha_name_hebrew": "וירא", "hebrew_year": 5787,
            "content": content, "generating": generating}


@pytest.fixture
def gen():
    with patch.object(dvar_torah, "_generate_dvar_torah", return_value=("On שבת (Shabbat) we learn.", METRICS)) as g:
        yield g


async def test_cached_text_is_served_without_generating(gen):
    with patch.object(dvar_torah.db, "get_dvar_torah", AsyncMock(return_value=row("Cached"))):
        result = await dvar_torah.get_or_generate_dvar_torah(None, "m", SHABBAT)
    assert result["content"] == "Cached"
    gen.assert_not_called()


async def test_stuck_placeholder_never_hangs_the_request(gen):
    # Another instance holds the slot and never finishes: the wait is bounded.
    with patch.object(dvar_torah.db, "get_dvar_torah", AsyncMock(return_value=row(generating=True))), \
         patch.object(dvar_torah.db, "claim_dvar_torah_generation", AsyncMock(return_value=None)) as claim:
        result = await dvar_torah.get_or_generate_dvar_torah(None, "m", SHABBAT, wait_seconds=0.05, poll_seconds=0.01)
    assert result is None
    assert claim.await_count >= 2
    gen.assert_not_called()


async def test_dead_placeholder_is_taken_over_and_completed(gen):
    # The claim retries while waiting; once the stale row can be taken over, this request generates.
    complete = AsyncMock(return_value=True)
    with patch.object(dvar_torah.db, "get_dvar_torah", AsyncMock(return_value=row(generating=True))), \
         patch.object(dvar_torah.db, "claim_dvar_torah_generation", AsyncMock(side_effect=[None, "row-1"])), \
         patch.object(dvar_torah.db, "complete_dvar_torah_generation", complete):
        result = await dvar_torah.get_or_generate_dvar_torah(None, "m", SHABBAT, wait_seconds=5, poll_seconds=0.01)
    assert "שבת" in result["content"]
    complete.assert_awaited_once_with("row-1", "On שבת (Shabbat) we learn.", METRICS)


async def test_failed_generation_releases_the_slot():
    fail = AsyncMock()
    with patch.object(dvar_torah, "_generate_dvar_torah", side_effect=RuntimeError("gateway down")), \
         patch.object(dvar_torah.db, "get_dvar_torah", AsyncMock(return_value=None)), \
         patch.object(dvar_torah.db, "claim_dvar_torah_generation", AsyncMock(return_value="row-1")), \
         patch.object(dvar_torah.db, "fail_dvar_torah_generation", fail):
        assert await dvar_torah.get_or_generate_dvar_torah(None, "m", SHABBAT) is None
    fail.assert_awaited_once_with("row-1")


async def test_regenerate_writes_new_text_in_one_step(gen):
    save = AsyncMock()
    delete = AsyncMock()
    with patch.object(dvar_torah.db, "save_dvar_torah", save), \
         patch.object(dvar_torah.db, "fail_dvar_torah_generation", delete):
        result = await dvar_torah.regenerate_dvar_torah(None, "m", SHABBAT)
    assert result["parsha_name"] == "Vayeira"
    save.assert_awaited_once_with("Vayeira", "וירא", 5787, "On שבת (Shabbat) we learn.", METRICS)
    delete.assert_not_awaited()


async def test_failed_regenerate_leaves_the_cache_alone():
    save = AsyncMock()
    with patch.object(dvar_torah, "_generate_dvar_torah", side_effect=RuntimeError("gateway down")), \
         patch.object(dvar_torah.db, "save_dvar_torah", save):
        with pytest.raises(RuntimeError):
            await dvar_torah.regenerate_dvar_torah(None, "m", SHABBAT)
    save.assert_not_awaited()

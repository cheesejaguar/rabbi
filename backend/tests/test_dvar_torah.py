"""Tests for weekly parsha selection in the d'var Torah module."""

from datetime import date, datetime, timezone
from unittest.mock import patch

from app.dvar_torah import get_current_parsha, resolve_local_date


class TestGetCurrentParsha:
    """Sunday-Thursday shows the parsha just read; Friday moves on."""

    def test_shabbat_is_its_own_parsha(self):
        # Shabbat 24 Oct 2026 is Shabbat Lech Lecha.
        assert get_current_parsha(date(2026, 10, 24))["parsha_name"] == "Lech Lecha"

    def test_sunday_through_thursday_keep_parsha_just_read(self):
        for day in range(25, 30):  # Sun 25 Oct - Thu 29 Oct
            assert get_current_parsha(date(2026, 10, day))["parsha_name"] == "Lech Lecha"

    def test_friday_moves_to_coming_parsha(self):
        assert get_current_parsha(date(2026, 10, 30))["parsha_name"] == "Vayeira"

    def test_after_holiday_shabbat_uses_coming_parsha(self):
        # Shabbat 3 Oct 2026 was Shemini Atzeret; the following week has
        # no parsha just read, so it shows Bereshit.
        assert get_current_parsha(date(2026, 10, 5))["parsha_name"] == "Bereishis"

    def test_holiday_week_returns_none(self):
        # Sunday of Sukkot week: both surrounding Shabbatot are yom tov.
        assert get_current_parsha(date(2026, 9, 27)) is None

    def test_hebrew_year(self):
        assert get_current_parsha(date(2026, 10, 24))["hebrew_year"] == 5787


class TestResolveLocalDate:
    # 03:42 UTC Friday is still Thursday evening across the Americas.
    UTC_NOW = datetime(2026, 10, 30, 3, 42, tzinfo=timezone.utc)

    def _resolve(self, client_date):
        with patch("app.dvar_torah.datetime") as mock_dt:
            mock_dt.now.return_value = self.UTC_NOW
            return resolve_local_date(client_date)

    def test_uses_client_date_behind_utc(self):
        assert self._resolve("2026-10-29") == date(2026, 10, 29)

    def test_uses_client_date_ahead_of_utc(self):
        assert self._resolve("2026-10-31") == date(2026, 10, 31)

    def test_accepts_full_iso_datetime(self):
        assert self._resolve("2026-10-29T20:42:00") == date(2026, 10, 29)

    def test_falls_back_to_utc_when_missing(self):
        assert self._resolve(None) == date(2026, 10, 30)

    def test_falls_back_to_utc_when_invalid(self):
        assert self._resolve("not-a-date") == date(2026, 10, 30)

    def test_rejects_dates_more_than_a_day_off(self):
        # Prevents requesting arbitrary weeks (and LLM generation for them).
        assert self._resolve("2026-11-13") == date(2026, 10, 30)
        assert self._resolve("2026-10-27") == date(2026, 10, 30)

    def test_thursday_evening_in_americas_keeps_parsha_just_read(self):
        local = self._resolve("2026-10-29")
        assert get_current_parsha(local)["parsha_name"] == "Lech Lecha"

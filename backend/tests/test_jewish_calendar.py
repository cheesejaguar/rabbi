"""Tests for jewish_calendar.py - Shabbat/yom tov awareness."""

from datetime import datetime

from app.jewish_calendar import get_calendar_status


class TestGetCalendarStatus:
    """Test Shabbat/yom tov detection for fixed known dates."""

    def test_ordinary_weekday_has_no_message(self):
        # Wednesday, July 1 2026 - nothing special
        status = get_calendar_status(datetime(2026, 7, 1, 12, 0))
        assert status["is_shabbat"] is False
        assert status["is_erev_shabbat"] is False
        assert status["is_yom_tov"] is False
        assert status["is_erev_yom_tov"] is False
        assert status["message"] is None

    def test_saturday_is_shabbat(self):
        # Saturday, July 4 2026, midday
        status = get_calendar_status(datetime(2026, 7, 4, 12, 0))
        assert status["is_shabbat"] is True
        assert "Shabbat" in status["message"]

    def test_saturday_night_after_havdalah_window(self):
        # Saturday night, after the conservative 20:00 cutoff
        status = get_calendar_status(datetime(2026, 7, 4, 21, 0))
        assert status["is_shabbat"] is False
        assert status["message"] is None

    def test_friday_afternoon_is_erev_shabbat(self):
        # Friday, July 3 2026, 5pm
        status = get_calendar_status(datetime(2026, 7, 3, 17, 0))
        assert status["is_erev_shabbat"] is True
        assert status["is_shabbat"] is False
        assert "sundown" in status["message"]

    def test_friday_morning_is_not_erev_shabbat(self):
        status = get_calendar_status(datetime(2026, 7, 3, 9, 0))
        assert status["is_erev_shabbat"] is False
        assert status["message"] is None

    def test_rosh_hashana_is_yom_tov(self):
        # Saturday, September 12 2026 = 1 Tishrei 5787 (Rosh Hashana)
        status = get_calendar_status(datetime(2026, 9, 12, 10, 0))
        assert status["is_yom_tov"] is True
        assert status["holiday_name"] == "Rosh Hashana"
        # Yom tov messaging takes precedence over the coinciding Shabbat
        assert "Rosh Hashana" in status["message"]

    def test_yom_kippur_gets_specific_message(self):
        # Monday, September 21 2026 = 10 Tishrei 5787 (Yom Kippur)
        status = get_calendar_status(datetime(2026, 9, 21, 10, 0))
        assert status["is_yom_tov"] is True
        assert status["holiday_name"] == "Yom Kippur"
        assert "fast" in status["message"]

    def test_pesach_first_day_is_yom_tov(self):
        # Thursday, April 2 2026 = 15 Nisan 5786 (Pesach I)
        status = get_calendar_status(datetime(2026, 4, 2, 10, 0))
        assert status["is_yom_tov"] is True
        assert status["holiday_name"] == "Pesach"

    def test_erev_yom_tov_detected(self):
        # Wednesday, April 1 2026, evening - the eve of Pesach I
        status = get_calendar_status(datetime(2026, 4, 1, 18, 0))
        assert status["is_erev_yom_tov"] is True
        assert status["holiday_name"] == "Pesach"
        assert "sundown" in status["message"]

    def test_chanukah_is_not_treated_as_yom_tov(self):
        # Chanukah 5787 begins Dec 5 2026 (25 Kislev); it is a working
        # holiday, so no melacha-restriction notice should appear.
        # Dec 7 2026 is a Monday within Chanukah.
        status = get_calendar_status(datetime(2026, 12, 7, 12, 0))
        assert status["is_yom_tov"] is False
        assert status["message"] is None

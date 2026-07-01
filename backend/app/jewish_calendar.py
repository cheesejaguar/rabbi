"""Shabbat and Yom Tov awareness for an observant audience.

Uses ``pyluach`` (already a dependency for parsha lookups) to determine
whether a given moment falls on Shabbat, a yom tov, or the eve of either.
The product does not block usage on these days -- users may be
non-observant, in another timezone, or in genuine need -- but the UI shows
a respectful notice, which both signals authenticity to observant users
and gently honors the rhythm of the calendar.

Timezone handling:
    Shabbat begins and ends at local sundown, which the server cannot know
    without the user's location. The client therefore sends its *local*
    date and time, and this module applies a conservative approximation:
    the eve begins at 16:00 local on Friday / erev yom tov, and the day
    itself is treated as lasting through 20:00 local the following day.
    The copy shown to users says "around sundown" -- never exact times.
"""

import logging
from datetime import datetime, timedelta

from pyluach import dates

logger = logging.getLogger(__name__)

# Local hour after which erev Shabbat / erev yom tov notices begin.
EVE_STARTS_HOUR = 16
# Local hour on the following day after which the day is considered over
# (a conservative havdalah approximation).
DAY_ENDS_HOUR = 20


def _yom_tov_name(pydate) -> str | None:
    """Return the festival name if the date is a yom tov, else ``None``.

    Uses ``include_working_days=False`` so only festivals on which melacha
    is traditionally prohibited are returned (e.g. Pesach I/VII, Shavuot,
    Rosh Hashana, Yom Kippur, Sukkot I, Shmini Atzeret, Simchat Torah) --
    not Chanukah, Purim, or chol hamoed.
    """
    heb = dates.HebrewDate.from_pydate(pydate)
    return heb.festival(israel=False, include_working_days=False)


def get_calendar_status(local_now: datetime) -> dict:
    """Compute Shabbat/yom tov status for a client-local datetime.

    Args:
        local_now: The user's local date and time (naive datetime built
            from the client's clock).

    Returns:
        A dict with:
            - ``is_shabbat`` (bool): It is currently Shabbat.
            - ``is_erev_shabbat`` (bool): Friday afternoon/evening before
              Shabbat.
            - ``is_yom_tov`` (bool): It is currently a yom tov.
            - ``is_erev_yom_tov`` (bool): Afternoon/evening before a yom tov.
            - ``holiday_name`` (str | None): The festival name when
              ``is_yom_tov`` or ``is_erev_yom_tov`` is set.
            - ``message`` (str | None): A ready-to-display notice, or
              ``None`` when there is nothing to show.
    """
    today = local_now.date()
    tomorrow = today + timedelta(days=1)
    hour = local_now.hour
    weekday = today.weekday()  # Monday=0 ... Saturday=5, Sunday=6

    # Saturday counts as Shabbat until the (approximate) end of the day;
    # Friday evening from EVE_STARTS_HOUR is treated as Shabbat itself is
    # near -- we call it erev rather than guessing candle-lighting.
    is_shabbat = weekday == 5 and hour < DAY_ENDS_HOUR
    is_erev_shabbat = weekday == 4 and hour >= EVE_STARTS_HOUR

    today_festival = _yom_tov_name(today)
    tomorrow_festival = _yom_tov_name(tomorrow)

    is_yom_tov = bool(today_festival) and hour < DAY_ENDS_HOUR
    is_erev_yom_tov = bool(tomorrow_festival) and hour >= EVE_STARTS_HOUR and not is_yom_tov

    holiday_name = None
    if is_yom_tov:
        holiday_name = today_festival
    elif is_erev_yom_tov:
        holiday_name = tomorrow_festival

    message = None
    if is_yom_tov and holiday_name == "Yom Kippur":
        message = (
            "G'mar chatima tova. It is Yom Kippur — a day for teshuvah, "
            "prayer, and presence. This conversation will be here after the fast."
        )
    elif is_yom_tov:
        message = (
            f"Chag sameach! It is {holiday_name}. Torah honors these days as "
            "a time set apart — this conversation will be here when yom tov ends."
        )
    elif is_shabbat:
        message = (
            "Shabbat shalom. It is Shabbat — a day of rest. "
            "This conversation will be here after havdalah."
        )
    elif is_erev_yom_tov:
        message = (
            f"{holiday_name} begins around sundown. "
            "Chag sameach — may it be a meaningful yom tov."
        )
    elif is_erev_shabbat:
        message = (
            "Shabbat begins around sundown. Shabbat shalom — "
            "may it be a peaceful one."
        )

    return {
        "is_shabbat": is_shabbat,
        "is_erev_shabbat": is_erev_shabbat,
        "is_yom_tov": is_yom_tov,
        "is_erev_yom_tov": is_erev_yom_tov,
        "holiday_name": holiday_name,
        "message": message,
    }

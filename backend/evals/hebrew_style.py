"""Check the "Hebrew letters first" style rule in generated answers.

The constitution asks English answers to write Hebrew/Aramaic terms as
Hebrew script followed by the transliteration in parentheses:
"שבת (Shabbat)". This module finds common transliterated terms that appear
*without* the Hebrew in front of them, so evals can measure adherence.
"""

import re

# Frequent terms whose bare transliteration signals a missed rule.
COMMON_TERMS = (
    "halacha", "halakha", "halachic", "mitzvah", "mitzvot", "shabbat", "shabbos", "tzedakah", "teshuvah",
    "tefillah", "talmud", "mishnah", "gemara", "rambam", "rashi", "shulchan aruch", "kashrut", "chesed",
    "pikuach nefesh", "shalom bayit", "lashon hara", "kavod habriyot", "minhag", "posek", "psak", "yom tov",
    "rosh hashanah", "yom kippur", "pesach", "sukkot", "chanukah", "kiddush", "havdalah", "tikkun olam",
)

_HEBREW = r"[֐-׿יִ-ﭏ]"
# Hebrew run (letters, gershayim/quotes, spaces, maqaf), then "(" right before the term.
_FORMATTED_PREFIX = re.compile(_HEBREW + r"[֐-׿יִ-ﭏ\"'״׳\s\-־]*\(\s*$")
_TERM = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(COMMON_TERMS, key=len, reverse=True)) + r")\b",
                   re.IGNORECASE)


def bare_transliterations(text: str) -> list[str]:
    """Common terms used without the Hebrew-first format, in order of appearance."""
    bare = []
    for m in _TERM.finditer(text or ""):
        before = text[max(0, m.start() - 40):m.start()]
        if not _FORMATTED_PREFIX.search(before):
            bare.append(m.group(1))
    return bare


def uses_hebrew_first(text: str) -> bool:
    """True when the answer contains at least one "עברית (transliteration)" pair."""
    return bool(re.search(_HEBREW + r"[֐-׿\"'״׳\s\-־]*\s\([A-Za-z]", text or ""))

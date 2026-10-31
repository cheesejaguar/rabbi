"""Weekly Torah commentary (d'var Torah) generation and caching.

Uses the ``pyluach`` library for Hebrew calendar computations to determine
which week's Torah portion (parsha) to feature: the one just read from
Sunday through Thursday, then the coming one on Friday and Shabbat. When a
d'var Torah is requested and no cached version exists for that parsha and
Hebrew year, the module generates one via an LLM call and stores the
result in the database for subsequent requests.

Caching strategy:
    Commentaries are cached by the composite key ``(parsha_name, hebrew_year)``.
    This means each parsha gets at most one generated commentary per year,
    and the same commentary is served to all users while that parsha is
    featured.

Concurrency control:
    To prevent duplicate LLM calls when multiple requests arrive
    simultaneously for an uncached parsha, the module uses an atomic
    "generation slot" claim via ``db.claim_dvar_torah_generation()``. Only
    the first request wins the slot and proceeds with generation; subsequent
    requests poll the cache until the generation completes or times out.
"""

import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from openai import OpenAI
from pyluach import dates, parshios

from . import database as db
from .agents.base import TOKEN_COSTS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

# The system prompt establishes the LLM's voice and structure for generating
# Torah commentaries. Key voice characteristics:
#   - Warm, confident, and unhurried -- as a rebbe speaking to his community
#     on Shabbat.
#   - Deeply sourced -- every idea is grounded in Torah, Talmud, Midrash,
#     Rambam, Zohar, and Chassidic masters.
#   - Accessible scholarship -- the teaching should nourish both a university
#     student and a grandmother.
#   - Flowing prose only -- no bullet points, headers, or markdown formatting.
#   - 400-600 words in length.
DVAR_TORAH_SYSTEM_PROMPT = """You are a Hasidic rebbe writing a weekly d'var Torah (Torah commentary) for your community.
Your voice is grounded in Torah, Talmud, Chassidus, and the full breadth of Jewish tradition.

VOICE: Write as a rebbe speaking to his community on Shabbat. Warm, confident, urgent yet
unhurried. Ground every idea in Torah sources -- Torah, Talmud, Midrash, Rambam, Zohar,
Chassidic masters. Weave sources seamlessly into the teaching.

STRUCTURE:
1. Open with a compelling question, tension, or observation from the parsha
2. Present a key verse or passage and a difficulty or question it raises
3. Bring at least 2-3 Torah sources (Rashi, Ramban, a Chassidic master, etc.) that shed light on the question
4. Resolve the tension by revealing a deeper layer of meaning
5. Bridge to a practical, relevant takeaway for modern Jewish life
6. Close with an uplifting connection to the person's own spiritual journey

LENGTH: 400-600 words. This should feel like a meaningful teaching, not a summary.

TONE: Simultaneously scholarly and accessible. A university student and a grandmother should
both feel nourished. Use concrete analogies from everyday life.

FORMATTING: Write as flowing prose, as if speaking. Do not use bullet points, headers,
numbered lists, or markdown formatting. Paragraphs only.

HEBREW TERMS — HEBREW LETTERS FIRST: Most readers are native English speakers who read little
Hebrew, and we want them to get used to Hebrew letters. Write every Hebrew or Aramaic term in
Hebrew script followed by its transliteration in parentheses, every time it appears, never
transliteration alone: שבת (Shabbat), תשובה (teshuvah), רש"י (Rashi), רמב"ן (Ramban),
בראשית (Bereshit). Add a short English gloss inside the parentheses when a beginner may not know
the word: חסד (chesed, loving-kindness). Use plain letters without vowel points. If you are
unsure of the Hebrew spelling of an uncommon name, give the transliteration alone. Plain English
words ("rabbi", "Sabbath") stay English. When you quote a verse, give the Hebrew first and then
the English translation.

AVOID: Do not include disclaimers about being an AI. This is a prepared teaching, not a
conversation. Do not use the word "delve"."""


def resolve_local_date(client_date: Optional[str]) -> date:
    """Pick the calendar date the weekly parsha should be computed from.

    The d'var Torah changes over at the start of the user's Friday, but
    the server runs in UTC, which reaches Friday while it is still
    Thursday evening in the Americas (and still Thursday afternoon on the
    US west coast). The client therefore sends its *local* date.

    Every timezone is within one day of UTC, so a client date further
    off than that is ignored. This also stops callers from requesting
    arbitrary weeks and triggering LLM generation for each one.

    Args:
        client_date: The client's local date as ``YYYY-MM-DD`` (longer
            ISO-8601 strings are truncated), or ``None``.

    Returns:
        The client's local date when valid, otherwise today's UTC date.
    """
    utc_today = datetime.now(timezone.utc).date()
    if client_date:
        try:
            local = date.fromisoformat(client_date[:10])
        except ValueError:
            local = None
        if local and abs((local - utc_today).days) <= 1:
            return local
    return utc_today


def _parsha_for(pydate: date) -> Optional[dict]:
    """Look up the parsha of the Shabbat on or after ``pydate``."""
    greg = dates.GregorianDate.from_pydate(pydate)
    # Returns None during holiday weeks (e.g., Pesach, Sukkot).
    english = parshios.getparsha_string(greg)
    if not english:
        return None
    hebrew = parshios.getparsha_string(greg, hebrew=True)
    return {
        "parsha_name": english,
        "parsha_name_hebrew": hebrew or "",
        "hebrew_year": greg.to_heb().year,
    }


def get_current_parsha(local_date: Optional[date] = None) -> Optional[dict]:
    """Determine which parsha's d'var Torah to show on a given day.

    The d'var Torah stays with the parsha just read for most of the week
    and moves to the coming parsha on erev Shabbat:

    - Friday and Shabbat: the parsha of this Shabbat.
    - Sunday through Thursday: the parsha read on the Shabbat just past.
      If that Shabbat had a holiday reading instead (e.g. chol hamoed),
      the coming Shabbat's parsha is used.

    Uses ``pyluach``, whose ``getparsha_string()`` returns the parsha of
    the Shabbat on or after a date, including double-parsha weeks.

    Args:
        local_date: The user's local date (see ``resolve_local_date``).
            Defaults to today's UTC date.

    Returns:
        A dictionary with keys:
            - ``parsha_name``: English transliteration (e.g., ``"Bereshit"``).
            - ``parsha_name_hebrew``: Hebrew name, or empty string if
              unavailable.
            - ``hebrew_year``: The Hebrew calendar year of that parsha's
              Shabbat as an integer (e.g., ``5786``).
        Returns ``None`` when no regular parsha applies (holiday weeks).
    """
    if local_date is None:
        local_date = resolve_local_date(None)

    weekday = local_date.weekday()  # Monday=0 ... Friday=4, Saturday=5, Sunday=6
    if weekday in (4, 5):
        return _parsha_for(local_date)

    last_shabbat = local_date - timedelta(days=(weekday - 5) % 7)
    return _parsha_for(last_shabbat) or _parsha_for(local_date)


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")


def clean_dvar_torah_content(content: str) -> str:
    """Strip markdown the LLM sometimes emits despite the prose-only prompt.

    The frontend renders the commentary as plain paragraphs, so markdown
    shows up literally (e.g. a ``# Parashat ...`` title). A heading on the
    first line duplicates the title the UI already shows and is dropped;
    any other heading keeps its text without the ``#`` markers. Bold
    markers (``**`` / ``__``) are removed.

    Applied when serving, so already-cached commentaries are cleaned too.
    """
    lines = content.strip().split("\n")
    if lines and _HEADING_RE.match(lines[0]):
        lines = lines[1:]
    lines = [_HEADING_RE.sub(r"\1", line) for line in lines]
    text = "\n".join(lines)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    return text.strip()


def _generate_dvar_torah(client: OpenAI, model: str, parsha_name: str, parsha_name_hebrew: str) -> tuple[str, dict]:
    """Generate a d'var Torah for a given parsha using a single LLM call.

    Constructs a user prompt requesting commentary on the specified parsha,
    sends it alongside the system prompt to the configured LLM, and
    collects token usage metrics for cost tracking.

    Args:
        client: An initialized ``OpenAI``-compatible API client (may point
            to OpenRouter or another gateway).
        model: The model identifier string (e.g.,
            ``"anthropic/claude-sonnet-5"``).
        parsha_name: The English transliteration of the parsha
            (e.g., ``"Bereshit"``).
        parsha_name_hebrew: The Hebrew name of the parsha for display
            in the prompt.

    Returns:
        A tuple of ``(content, metrics)`` where:
            - ``content``: The generated d'var Torah text.
            - ``metrics``: A dictionary with ``input_tokens``,
              ``output_tokens``, ``latency_ms``, ``estimated_cost_usd``,
              and ``model``.
    """
    user_prompt = (
        f"Write a d'var Torah for Parashat {parsha_name} ({parsha_name_hebrew}).\n\n"
        "This is this week's Torah portion. Create an original, "
        "insightful teaching that illuminates a central theme of this parsha."
    )

    messages = [
        {"role": "system", "content": DVAR_TORAH_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    start_time = time.time()
    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=messages,
    )
    latency_ms = int((time.time() - start_time) * 1000)

    input_tokens = getattr(response.usage, 'prompt_tokens', 0) if response.usage else 0
    output_tokens = getattr(response.usage, 'completion_tokens', 0) if response.usage else 0

    # Estimate cost based on per-model token pricing from the agent config.
    costs = TOKEN_COSTS.get(model, TOKEN_COSTS["default"])
    estimated_cost = round(
        (input_tokens / 1_000_000) * costs["input"] + (output_tokens / 1_000_000) * costs["output"],
        6
    )

    content = response.choices[0].message.content
    metrics = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "estimated_cost_usd": estimated_cost,
        "model": model,
    }

    return content, metrics


def _result(parsha_name: str, parsha_name_hebrew: str, hebrew_year: int, content: str) -> dict:
    return {
        "parsha_name": parsha_name,
        "parsha_name_hebrew": parsha_name_hebrew,
        "hebrew_year": hebrew_year,
        "content": clean_dvar_torah_content(content),
    }


def _ready(row: Optional[dict]) -> bool:
    return bool(row and not row["generating"] and row["content"])


async def get_or_generate_dvar_torah(
    client: OpenAI, model: str, local_date: Optional[date] = None,
    wait_seconds: float = 40, poll_seconds: float = 2,
) -> Optional[dict]:
    """Get the current week's d'var Torah, generating it if not yet cached.

    1. Return the cached commentary when there is one.
    2. Otherwise try to claim the generation slot (``db.claim_dvar_torah_generation``,
       an atomic upsert that also takes over a dead placeholder). The winner
       generates the text off the event loop and stores it.
    3. Everyone else polls the cache until ``wait_seconds`` runs out, trying
       the claim again on each poll in case the winner died.

    Returns ``None`` during holiday weeks or when generation fails or times
    out; the caller shows its fallback. The wait is bounded, so a stuck row
    can never hang a request.
    """
    parsha = get_current_parsha(local_date)
    if not parsha:
        return None

    parsha_name = parsha["parsha_name"]
    parsha_name_hebrew = parsha["parsha_name_hebrew"]
    hebrew_year = parsha["hebrew_year"]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        cached = await db.get_dvar_torah(parsha_name, hebrew_year)
        if _ready(cached):
            return _result(cached["parsha_name"], cached["parsha_name_hebrew"], cached["hebrew_year"],
                           cached["content"])

        row_id = await db.claim_dvar_torah_generation(parsha_name, parsha_name_hebrew, hebrew_year)
        if row_id:
            break
        if loop.time() >= deadline:
            logger.warning("Timed out waiting for d'var Torah generation for %s", parsha_name)
            return None
        await asyncio.sleep(poll_seconds)

    try:
        logger.info("Generating d'var Torah for Parashat %s", parsha_name)
        content, metrics = await asyncio.to_thread(
            _generate_dvar_torah, client, model, parsha_name, parsha_name_hebrew)
        if not content or not content.strip():
            raise ValueError("model returned an empty d'var Torah")
        if not await db.complete_dvar_torah_generation(row_id, content, metrics):
            logger.warning("D'var Torah placeholder for %s was replaced while generating", parsha_name)
        logger.info("D'var Torah generated for Parashat %s (%sms)", parsha_name, metrics["latency_ms"])
        return _result(parsha_name, parsha_name_hebrew, hebrew_year, content)
    except Exception as e:
        logger.error("Failed to generate d'var Torah for %s: %s", parsha_name, e)
        await db.fail_dvar_torah_generation(row_id)
        return None


async def regenerate_dvar_torah(client: OpenAI, model: str, local_date: Optional[date] = None) -> Optional[dict]:
    """Write this week's d'var Torah again and replace the cached one (admin).

    The new text is generated first and stored in one atomic upsert, so
    readers keep the old text until the new one is ready and a failed or
    repeated regeneration never leaves the cache empty or stuck. Raises on
    generation failure; returns ``None`` in a holiday week.
    """
    parsha = get_current_parsha(local_date)
    if not parsha:
        return None
    parsha_name, parsha_name_hebrew, hebrew_year = (
        parsha["parsha_name"], parsha["parsha_name_hebrew"], parsha["hebrew_year"])
    content, metrics = await asyncio.to_thread(
        _generate_dvar_torah, client, model, parsha_name, parsha_name_hebrew)
    if not content or not content.strip():
        raise ValueError("model returned an empty d'var Torah")
    await db.save_dvar_torah(parsha_name, parsha_name_hebrew, hebrew_year, content, metrics)
    logger.info("D'var Torah regenerated for Parashat %s (%sms)", parsha_name, metrics["latency_ms"])
    return _result(parsha_name, parsha_name_hebrew, hebrew_year, content)

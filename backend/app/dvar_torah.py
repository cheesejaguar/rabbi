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


async def get_or_generate_dvar_torah(
    client: OpenAI, model: str, local_date: Optional[date] = None
) -> Optional[dict]:
    """Get the current week's d'var Torah, generating it if not yet cached.

    Orchestrates the full lifecycle of d'var Torah retrieval:

    1. **Parsha lookup**: Determines which parsha to show today (see
       ``get_current_parsha``). Returns ``None`` during holiday weeks.
    2. **Cache check**: Queries the database for an existing, completed
       commentary for this parsha and Hebrew year.
    3. **Generation-in-progress wait**: If another request is already
       generating the commentary (``generating=True``), polls the cache
       every 2 seconds for up to 30 seconds before giving up.
    4. **Atomic slot claim**: Calls ``db.claim_dvar_torah_generation()``
       which performs an atomic INSERT (or returns ``None`` if another
       request claimed the slot first). This prevents duplicate concurrent
       LLM calls -- only one request will proceed with generation.
    5. **LLM generation**: Calls ``_generate_dvar_torah()`` and stores
       the result via ``db.complete_dvar_torah_generation()``.
    6. **Failure handling**: On generation error, marks the slot as
       failed via ``db.fail_dvar_torah_generation()`` so future requests
       can retry.

    Args:
        client: An initialized ``OpenAI``-compatible API client.
        model: The model identifier string for generation.
        local_date: The user's local date, used to pick the week's parsha.

    Returns:
        A dictionary with ``parsha_name``, ``parsha_name_hebrew``,
        ``hebrew_year``, and ``content``, or ``None`` during holiday
        weeks or if generation fails/times out.
    """
    parsha = get_current_parsha(local_date)
    if not parsha:
        return None

    parsha_name = parsha["parsha_name"]
    parsha_name_hebrew = parsha["parsha_name_hebrew"]
    hebrew_year = parsha["hebrew_year"]

    # Check cache for an already-completed commentary.
    cached = await db.get_dvar_torah(parsha_name, hebrew_year)
    if cached and not cached["generating"] and cached["content"]:
        return {
            "parsha_name": cached["parsha_name"],
            "parsha_name_hebrew": cached["parsha_name_hebrew"],
            "hebrew_year": cached["hebrew_year"],
            "content": cached["content"],
        }

    # If another request is already generating, wait and retry.
    # Poll every 2 seconds for up to 30 seconds (15 iterations).
    if cached and cached["generating"]:
        for _ in range(15):
            await asyncio.sleep(2)
            cached = await db.get_dvar_torah(parsha_name, hebrew_year)
            if cached and not cached["generating"] and cached["content"]:
                return {
                    "parsha_name": cached["parsha_name"],
                    "parsha_name_hebrew": cached["parsha_name_hebrew"],
                    "hebrew_year": cached["hebrew_year"],
                    "content": cached["content"],
                }
        # Timed out waiting - return None to show fallback
        logger.warning(f"Timed out waiting for d'var Torah generation for {parsha_name}")
        return None

    # Claim the generation slot atomically.
    # claim_dvar_torah_generation() performs an atomic database INSERT that
    # succeeds only if no row exists for this (parsha_name, hebrew_year).
    # If another request claimed the slot between our cache check and this
    # call, it returns None, and we retry from the cache.
    row_id = await db.claim_dvar_torah_generation(parsha_name, parsha_name_hebrew, hebrew_year)
    if not row_id:
        # Another request claimed it first, retry from cache
        await asyncio.sleep(2)
        return await get_or_generate_dvar_torah(client, model, local_date)

    # Generate the d'var Torah via LLM.
    try:
        logger.info(f"Generating d'var Torah for Parashat {parsha_name}")
        content, metrics = _generate_dvar_torah(client, model, parsha_name, parsha_name_hebrew)
        await db.complete_dvar_torah_generation(row_id, content, metrics)
        logger.info(f"D'var Torah generated for Parashat {parsha_name} ({metrics['latency_ms']}ms)")
        return {
            "parsha_name": parsha_name,
            "parsha_name_hebrew": parsha_name_hebrew,
            "hebrew_year": hebrew_year,
            "content": content,
        }
    except Exception as e:
        # Mark the generation slot as failed so future requests can retry.
        logger.error(f"Failed to generate d'var Torah for {parsha_name}: {e}")
        await db.fail_dvar_torah_generation(row_id)
        return None

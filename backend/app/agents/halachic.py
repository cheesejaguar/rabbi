"""Halachic Reasoning Agent - Engages halacha as a living, pluralistic legal system."""

import json
import logging
import re
from typing import Optional
from ..config import DEFAULT_LLM_MODEL
from .base import (
    BaseAgent,
    AgentContext,
    HalachicLandscape,
    PastoralMode,
)
from .denominations import get_denomination_config
from .rag import TextRetriever

logger = logging.getLogger(__name__)

# Keywords/phrases that indicate the question would benefit from source texts.
# Kept as sets/tuples for fast membership testing.
_RAG_TRIGGER_KEYWORDS = {
    # Halachic / legal terms
    "halacha", "halachic", "halakha", "halakhic", "halachot",
    "shulchan aruch", "shulchan arukh", "mishnah", "mishna",
    "gemara", "talmud", "rambam", "maimonides", "rashi",
    "tosafot", "tosefta", "midrash",
    "torah", "tanakh", "tanach", "chumash", "bereishit", "shemot",
    "vayikra", "bamidbar", "devarim",
    "pasuk", "posek", "poskim", "psak", "teshuva", "teshuvot", "responsa",
    # Practice terms
    "shabbat", "shabbos", "kashrut", "kosher", "treif", "treyf",
    "tefillin", "tzitzit", "mezuzah", "mikveh", "mikvah",
    "daven", "davening", "tefillah", "bracha", "brachot", "berakhot",
    "kiddush", "havdalah", "netilat", "niddah", "taharat",
    "eruv", "sukkah", "lulav", "etrog", "shofar", "megillah",
    "brit milah", "pidyon haben",
    # Lifecycle / family law
    "marriage", "divorce", "get", "ketubah", "kiddushin",
    "mourning", "shiva", "avelut", "kaddish",
    "conversion", "giyur", "beit din",
    # Ethical / theological concepts
    "mitzvah", "mitzvot", "aveirah", "teshuvah",
    "pikuach nefesh", "kavod habriyot",
    "mutar", "assur", "permitted", "forbidden", "obligated",
    # Source request signals
    "source", "sources", "what does the", "according to",
    "cite", "citation", "reference",
    "what do the rabbis say", "rabbinic", "chazal",
}

# Short messages that are clearly not text-related (greetings, thanks, etc.)
_SKIP_PATTERNS = re.compile(
    r"^(hi|hello|hey|shalom|thanks|thank you|toda|todah|bye|goodbye"
    r"|good morning|good evening|good night|boker tov|laila tov"
    r"|how are you|what is this|who are you|what can you do"
    r"|ok|okay|sure|yes|no|got it|understood|i see)[.!?\s]*$",
    re.IGNORECASE,
)


def _should_use_rag(user_message: str, pastoral_mode: Optional[PastoralMode] = None) -> bool:
    """
    Determine whether RAG retrieval should be used for this message.

    RAG is used sparingly - only when the question would genuinely benefit
    from grounding in primary source texts:
      - User explicitly asks about texts or sources
      - Question involves halachic concepts, practices, or Torah topics
      - Pastoral mode is teaching or curiosity (knowledge-seeking)

    RAG is skipped for:
      - Crisis mode (focus on emotional support, not sources)
      - Greetings, thanks, and casual conversation
      - Messages with no halachic or textual substance
    """
    msg = user_message.strip()

    # Very short or empty messages never need RAG
    if len(msg) < 5:
        return False

    # Skip patterns: greetings, thanks, meta-questions about the bot
    if _SKIP_PATTERNS.match(msg):
        return False

    # Crisis mode: focus on emotional support, not source texts
    if pastoral_mode == PastoralMode.CRISIS:
        return False

    # Check if message contains any RAG trigger keywords
    msg_lower = msg.lower()
    for keyword in _RAG_TRIGGER_KEYWORDS:
        if keyword in msg_lower:
            return True

    # For teaching/curiosity modes, also trigger RAG on question patterns
    # about Jewish topics even without exact keyword matches
    if pastoral_mode in (PastoralMode.TEACHING, PastoralMode.CURIOSITY):
        # Questions about "is it", "can I", "should I", "am I allowed" suggest practice questions
        practice_patterns = re.compile(
            r"\b(is it|can i|should i|am i allowed|do i need to|do i have to"
            r"|is there a|what is the law|what are the rules"
            r"|pray|fasting|fast|sabbath|holiday|yom tov|pesach|passover"
            r"|sukkot|chanukah|hanukkah|purim|rosh hashana|yom kippur"
            r"|jewish|judaism|rabbi|rebbe|god|hashem|adonai)\b",
            re.IGNORECASE,
        )
        if practice_patterns.search(msg):
            return True

    return False


class HalachicReasoningAgent(BaseAgent):
    """
    The Halachic Reasoning Agent engages with Jewish law as a living,
    pluralistic legal system. It presents ranges of opinion rather than
    single conclusions and explicitly labels different categories of law.

    When a TextRetriever is available, the agent retrieves relevant source
    texts from the library to ground its analysis in primary sources.
    """

    def __init__(self, client, model: str = DEFAULT_LLM_MODEL,
                 retriever: Optional[TextRetriever] = None):
        super().__init__(client, model)
        self.retriever = retriever

    @property
    def system_prompt(self) -> str:
        return """You are the Halachic Reasoning Agent for rebbe.dev operating within a progressive Modern Orthodox framework.

Your role is to engage with halacha (Jewish law) as a LIVING, PLURALISTIC legal system. You must present the full landscape of halachic opinion, not collapse it into a single answer.

KNOWLEDGE DOMAINS:
- Talmud (sugya-based reasoning)
- Rambam (Maimonides) and Shulchan Aruch
- Classical responsa (Teshuvot)
- Modern responsa and poskim
- Minority and rejected opinions (explicitly labeled as such)

REASONING REQUIREMENTS:
1. Present RANGES of opinion, not single conclusions
2. Explicitly label:
   - De'oraita (Biblical) vs. derabbanan (Rabbinic)
   - Minhag (custom) vs. strict law
   - Normative vs. exceptional rulings
   - Majority vs. minority positions
3. Identify underlying principles that inform the discussion
4. Note precedents for leniency when they exist
5. Acknowledge non-negotiable boundaries honestly

QUESTION TYPE AWARENESS:
Not every question requires a full halachic landscape analysis. Check the pastoral context for the question_type field:
- If question_type is "factual" or "historical": Provide a DIRECT, informative answer. Use "majority_view" for your direct factual answer, "minority_views" for alternative perspectives or additional context, "underlying_principles" for key themes, and "sources_cited" for references. Leave "precedents_for_leniency" and "non_negotiable_boundaries" as empty lists.
- If question_type is "halachic": Use the full landscape analysis as described above.
- If question_type is "personal": Focus on the aspects most relevant to the person's situation.
Do NOT force a halachic framework onto questions that are asking for facts or history.

Given the user's question and the pastoral context, provide a halachic landscape analysis.

CRITICAL: Adjust your response based on the pastoral context:
- If vulnerability is detected, lead with compassion and emphasize lenient opinions
- If in crisis mode, focus on immediate practical guidance and human referral
- If in teaching mode, you may be more comprehensive
- If in curiosity mode, engage intellectually while remaining warm

Output a JSON object with:
{
  "majority_view": "Description of the mainstream halachic position",
  "minority_views": ["List of notable minority or lenient opinions"],
  "underlying_principles": ["Key halachic/ethical principles at play"],
  "precedents_for_leniency": ["Sources or concepts that support lenient approaches"],
  "non_negotiable_boundaries": ["Clear boundaries that cannot be crossed"],
  "sources_cited": ["Brief references to sources mentioned"],
  "summary_for_user": "A warm, accessible summary appropriate to the pastoral context",
  "reasoning": "Brief explanation of your analysis"
}

IMPORTANT PRINCIPLES:
- "Koach d'hetera adif" - The power of leniency is preferred when justified
- "Lo nitna Torah l'malachei hashareit" - Torah was not given to angels
- "Gadol kavod habriyot" - Great is human dignity
- Never present a stringent opinion as the only option when lenient ones exist
- Always remember there is a person behind the question

When providing your analysis, focus on the halachic substance. Do NOT embed references to the user's personal background, denomination name, or bio in your JSON output fields.

Respond ONLY with the JSON object, no additional text."""

    async def process(self, context: AgentContext) -> AgentContext:
        """Analyze the halachic dimensions of the user's question."""

        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT (from Pastoral Agent - this guides your approach):
- Mode: {pc.mode.value}
- Question type: {pc.question_type}
- Tone required: {pc.tone.value}
- Authority level: {pc.authority_level.value}
- Vulnerability detected: {pc.vulnerability_detected}
- Emotional state: {pc.emotional_state}
- Crisis indicators: {pc.crisis_indicators}

CRITICAL: If vulnerability is detected AND the question_type is "personal" or "halachic", lead with compassion and emphasize paths of leniency. If the question_type is "factual" or "historical", answer the question directly — the person asked for information, not counseling.
"""

        # Build denomination-specific guidance
        denomination_info = ""
        if context.user_denomination:
            config = get_denomination_config(context.user_denomination)
            if config:
                sources_list = "\n  - ".join(config.primary_sources)
                denomination_info = f"""
USER'S DENOMINATIONAL CONTEXT: {config.display_name}
The user identifies with {config.display_name} Judaism. Tailor your response accordingly:

PRIMARY SOURCES TO EMPHASIZE:
  - {sources_list}

HALACHIC APPROACH FOR THIS DENOMINATION:
{config.halachic_stance}

LENIENCY APPROACH: {config.leniency_bias}
{config.source_approach}
"""

        # Add user bio context if available (marked as internal-only)
        user_bio_info = ""
        if context.user_bio:
            user_bio_info = f"\n[INTERNAL CONTEXT — for calibrating your analysis, do NOT embed user background details in your JSON output] User bio: {context.user_bio}\n"

        # RAG: Retrieve relevant source texts only when the question warrants it
        retrieved_sources = ""
        pastoral_mode = context.pastoral_context.mode if context.pastoral_context else None
        use_rag = _should_use_rag(context.user_message, pastoral_mode)
        context.metadata["rag_used"] = use_rag

        if self.retriever and use_rag:
            # Lazily ensure index is loaded (handles Vercel where lifespan doesn't fire)
            self.retriever.ensure_loaded()
            retrieved_sources = self.retriever.search_formatted(
                context.user_message, top_k=5
            )
            if retrieved_sources:
                retrieved_sources = f"""
RELEVANT SOURCE TEXTS FROM LIBRARY:
The following primary source texts were retrieved from the Jewish texts library and may be relevant to this question. Use them to ground your analysis in actual sources. Cite specific passages when applicable.

{retrieved_sources}
"""
                logger.info("RAG: Retrieved %d chars of source text for halachic analysis",
                            len(retrieved_sources))
        elif not use_rag:
            logger.info("RAG: Skipped retrieval (message does not warrant source texts)")

        messages = [
            {
                "role": "user",
                "content": f"""{pastoral_info}{denomination_info}{user_bio_info}{retrieved_sources}
USER'S QUESTION:
{context.user_message}

Provide a halachic landscape analysis for this question, adjusted appropriately for the pastoral context{" and the user's denominational background" if denomination_info else ""}."""
            }
        ]

        response, metrics = self._call_claude(messages, self.system_prompt)
        self._update_context_metrics(context, metrics)

        halachic_landscape = self._parse_response(response)
        context.halachic_landscape = halachic_landscape

        if halachic_landscape.majority_view:
            context.intermediate_response = halachic_landscape.majority_view

        return context

    def _parse_response(self, response: str) -> HalachicLandscape:
        """Parse the Claude response into a HalachicLandscape object."""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response)

            landscape = HalachicLandscape(
                majority_view=data.get("majority_view", ""),
                minority_views=data.get("minority_views", []),
                underlying_principles=data.get("underlying_principles", []),
                precedents_for_leniency=data.get("precedents_for_leniency", []),
                non_negotiable_boundaries=data.get("non_negotiable_boundaries", []),
                sources_cited=data.get("sources_cited", []),
            )

            if "summary_for_user" in data:
                landscape.majority_view = data["summary_for_user"]

            return landscape

        except (json.JSONDecodeError, ValueError, KeyError):
            return HalachicLandscape(
                majority_view="I want to give you a thoughtful answer, but I need to be careful here. This is a question that deserves more nuance than I can provide in this moment.",
                underlying_principles=["Human dignity", "Seeking guidance from a human rabbi"],
            )

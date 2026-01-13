"""Halachic Reasoning Agent - Engages halacha as a living, pluralistic legal system."""

import json
import re
from .base import (
    BaseAgent,
    AgentContext,
    HalachicLandscape,
)


class HalachicReasoningAgent(BaseAgent):
    """
    The Halachic Reasoning Agent engages with Jewish law as a living,
    pluralistic legal system. It presents ranges of opinion rather than
    single conclusions and explicitly labels different categories of law.
    """

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

Respond ONLY with the JSON object, no additional text."""

    async def process(self, context: AgentContext) -> AgentContext:
        """Analyze the halachic dimensions of the user's question."""

        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT (from Pastoral Agent - this guides your approach):
- Mode: {pc.mode.value}
- Tone required: {pc.tone.value}
- Authority level: {pc.authority_level.value}
- Vulnerability detected: {pc.vulnerability_detected}
- Emotional state: {pc.emotional_state}
- Crisis indicators: {pc.crisis_indicators}

CRITICAL: If vulnerability is detected, you MUST lead with compassion and emphasize paths of leniency.
"""

        messages = [
            {
                "role": "user",
                "content": f"""{pastoral_info}

USER'S QUESTION:
{context.user_message}

Provide a halachic landscape analysis for this question, adjusted appropriately for the pastoral context."""
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

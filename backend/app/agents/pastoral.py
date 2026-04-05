"""Pastoral Context Agent -- determines HOW to answer before WHAT to answer.

This is the **first** agent in the pipeline.  It analyses the user's message
for emotional state, vulnerability, and crisis indicators, then produces a
``PastoralContext`` that constrains every downstream agent.  Crucially, when
vulnerability is detected the resulting context prohibits halachic maximalism
in the HalachicReasoningAgent and requires a gentle, validating tone from the
MetaRabbinicVoiceAgent.

Expected LLM JSON output schema::

    {
      "mode":                   "teaching" | "counseling" | "crisis" | "curiosity",
      "tone":                   "gentle" | "firm" | "exploratory" | "validating",
      "authority_level":        "definitive" | "suggestive" | "exploratory",
      "vulnerability_detected": bool,
      "crisis_indicators":      list[str],
      "emotional_state":        str,
      "requires_human_referral": bool,
      "reasoning":              str
    }
"""

import json
import re
from .base import (
    BaseAgent,
    AgentContext,
    PastoralContext,
    PastoralMode,
    ToneConstraint,
    AuthorityLevel,
)


class PastoralContextAgent(BaseAgent):
    """First pipeline agent -- highest priority in the system.

    Determines the emotional and situational context before any halachic or
    moral reasoning takes place.

    Key responsibility: if vulnerability is detected, halachic maximalism is
    prohibited downstream.  *"A psak that breaks a person is not Torah."*
    """

    @property
    def system_prompt(self) -> str:
        return """You are the Pastoral Context Agent for rebbe.dev operating within a progressive Modern Orthodox framework.

Your role is to analyze the user's message and determine HOW to respond before determining WHAT to answer. You have the highest priority in the system.

CRITICAL PRINCIPLE: "A psak that breaks a person is not Torah."

Analyze the following dimensions:

1. EMOTIONAL STATE
   - Explicit emotions expressed
   - Implicit emotional undertones
   - Signs of distress, shame, doubt, grief, or fear

2. LIFE CONTEXT
   - Grief or loss
   - Religious doubt or crisis
   - Shame or guilt
   - Curiosity and learning
   - Interpersonal conflict
   - Identity questions

3. RISK INDICATORS
   - Mental health concerns
   - Signs of coercion or abuse
   - Trauma indicators
   - Self-harm risk
   - Isolation from community

4. POWER DYNAMICS
   - Is the person feeling judged?
   - Are they seeking validation or information?
   - What is their relationship to Jewish practice?

5. QUESTION TYPE CLASSIFICATION
   Determine the nature of the question itself:
   - "factual": Asks for facts, definitions, explanations of concepts (e.g., "What is Shabbat?", "Who was Maimonides?")
   - "historical": Asks about historical events, speeches, figures, timelines (e.g., "What was the Rebbe's most impactful speech?", "When did the Temple fall?")
   - "halachic": Asks about Jewish law, practice, what is permitted/forbidden (e.g., "Can I eat dairy after meat?", "Is it okay to drive on Shabbat?")
   - "personal": Expresses personal struggle, seeks emotional guidance, or asks about their own situation (e.g., "I feel disconnected from Judaism", "My family doesn't accept me")

   CRITICAL: If the question is factual or historical, mode should almost always be "curiosity" or "teaching", NOT "counseling". Do not infer personal struggle from intellectual questions.

Based on your analysis, output a JSON object with:
{
  "mode": "teaching" | "counseling" | "crisis" | "curiosity",
  "question_type": "factual" | "historical" | "halachic" | "personal",
  "tone": "gentle" | "firm" | "exploratory" | "validating",
  "authority_level": "definitive" | "suggestive" | "exploratory",
  "vulnerability_detected": true | false,
  "crisis_indicators": ["list of any crisis signs detected"],
  "emotional_state": "emotional tone detected in THIS MESSAGE ONLY (e.g., anxious, curious, grieving — do not paraphrase the user's bio or background)",
  "requires_human_referral": true | false,
  "reasoning": "brief explanation of your assessment"
}

HARD RULES:
- If ANY vulnerability is detected, set vulnerability_detected to true
- If vulnerability is detected, authority_level MUST be "suggestive" or "exploratory"
- If crisis indicators are present, requires_human_referral should be true
- When in doubt about whether someone is vulnerable, err on the side of gentleness
- When in doubt about whether a question is factual or personal, err on the side of treating it as factual — respect the question as asked
- Many questions ARE purely intellectual, historical, or factual. Do not project emotional motivations onto questions that don't express them. Reserve "counseling" mode for messages that express personal struggle or explicitly ask for personal guidance.

Respond ONLY with the JSON object, no additional text."""

    async def process(self, context: AgentContext) -> AgentContext:
        """Analyse the user's message to determine pastoral context.

        Sends the user message (with optional denomination/bio and recent
        conversation history) to the LLM, then parses the JSON response
        into a ``PastoralContext`` stored on ``context.pastoral_context``.

        The resulting ``PastoralContext`` propagates to every downstream
        agent.  In particular, ``vulnerability_detected=True`` forces the
        HalachicReasoningAgent to suppress maximalism and lead with
        compassion.

        Args:
            context: The shared pipeline context.  Only ``user_message``,
                ``conversation_history``, ``user_denomination``, and
                ``user_bio`` are read.

        Returns:
            The same context with ``pastoral_context`` populated.
        """

        # Build user background context from profile
        user_background = ""
        if context.user_denomination or context.user_bio:
            user_background = "\n\nUSER BACKGROUND:"
            if context.user_denomination:
                user_background += f"\n- Denomination: {context.user_denomination}"
            if context.user_bio:
                user_background += f"\n- Bio: {context.user_bio}"
            user_background += "\nConsider what vulnerability and appropriate tone mean for someone from this background."

        messages = [
            {
                "role": "user",
                "content": f"Analyze this message for pastoral context:\n\n{context.user_message}{user_background}"
            }
        ]

        if context.conversation_history:
            history_summary = "\n".join([
                f"{msg['role']}: {msg['content'][:200]}..."
                for msg in context.conversation_history[-3:]
            ])
            messages[0]["content"] += f"\n\nRecent conversation context:\n{history_summary}"

        response, metrics = self._call_claude(messages, self.system_prompt)
        self._update_context_metrics(context, metrics)

        pastoral_context = self._parse_response(response)
        context.pastoral_context = pastoral_context

        return context

    def _parse_response(self, response: str) -> PastoralContext:
        """Parse the LLM's JSON response into a ``PastoralContext``.

        Attempts to extract a JSON object from the response text (the LLM
        sometimes wraps it in markdown fences).  On any parse failure,
        returns a *safe default* context with vulnerability set to True and
        a gentle tone -- erring on the side of caution.

        Args:
            response: Raw text output from the LLM.

        Returns:
            A populated ``PastoralContext`` instance.
        """
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response)

            return PastoralContext(
                mode=PastoralMode(data.get("mode", "curiosity")),
                tone=ToneConstraint(data.get("tone", "exploratory")),
                authority_level=AuthorityLevel(data.get("authority_level", "suggestive")),
                vulnerability_detected=data.get("vulnerability_detected", False),
                crisis_indicators=data.get("crisis_indicators", []),
                emotional_state=data.get("emotional_state", "neutral"),
                requires_human_referral=data.get("requires_human_referral", False),
                question_type=data.get("question_type", "personal"),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return PastoralContext(
                mode=PastoralMode.CURIOSITY,
                tone=ToneConstraint.GENTLE,
                authority_level=AuthorityLevel.SUGGESTIVE,
                vulnerability_detected=True,
                emotional_state="uncertain - defaulting to gentle approach",
                question_type="personal",
            )

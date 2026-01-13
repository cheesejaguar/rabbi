"""Pastoral Context Agent - Determines HOW to answer before WHAT to answer."""

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
    """
    The Pastoral Context Agent has the highest priority in the system.
    It determines the emotional and situational context before any
    halachic or moral reasoning takes place.

    Key responsibility: If vulnerability is detected, halachic maximalism is prohibited.
    "A psak that breaks a person is not Torah."
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

Based on your analysis, output a JSON object with:
{
  "mode": "teaching" | "counseling" | "crisis" | "curiosity",
  "tone": "gentle" | "firm" | "exploratory" | "validating",
  "authority_level": "definitive" | "suggestive" | "exploratory",
  "vulnerability_detected": true | false,
  "crisis_indicators": ["list of any crisis signs detected"],
  "emotional_state": "description of detected emotional state",
  "requires_human_referral": true | false,
  "reasoning": "brief explanation of your assessment"
}

HARD RULES:
- If ANY vulnerability is detected, set vulnerability_detected to true
- If vulnerability is detected, authority_level MUST be "suggestive" or "exploratory"
- If crisis indicators are present, requires_human_referral should be true
- When in doubt, err on the side of gentleness and validation
- Never assume a question is purely intellectual - there is often a person behind the question

Respond ONLY with the JSON object, no additional text."""

    async def process(self, context: AgentContext) -> AgentContext:
        """Analyze the user's message to determine pastoral context."""

        messages = [
            {
                "role": "user",
                "content": f"Analyze this message for pastoral context:\n\n{context.user_message}"
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
        """Parse the Claude response into a PastoralContext object."""
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
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return PastoralContext(
                mode=PastoralMode.CURIOSITY,
                tone=ToneConstraint.GENTLE,
                authority_level=AuthorityLevel.SUGGESTIVE,
                vulnerability_detected=True,
                emotional_state="uncertain - defaulting to gentle approach",
            )

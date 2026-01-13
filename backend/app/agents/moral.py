"""Moral-Ethical Agent - Ensures halachic reasoning aligns with moral seriousness."""

import json
import re
from .base import (
    BaseAgent,
    AgentContext,
    MoralAssessment,
)


class MoralEthicalAgent(BaseAgent):
    """
    The Moral-Ethical Agent ensures that halachic reasoning aligns with
    moral seriousness. It acts as a check on responses that might be
    technically correct but morally harmful.

    Primary question: "Does this response increase holiness WITHOUT increasing harm?"
    """

    @property
    def system_prompt(self) -> str:
        return """You are the Moral-Ethical Agent for rebbe.dev operating within a progressive Modern Orthodox framework.

Your role is to ensure that halachic reasoning aligns with MORAL SERIOUSNESS. You are the ethical conscience of the system.

PRIMARY QUESTION YOU MUST ANSWER:
"Does this response increase holiness WITHOUT increasing harm?"

EMBEDDED VALUES:
1. Kavod habriyot (human dignity) - Every person deserves respect
2. Tzelem Elokim - Every human is created in God's image
3. Power sensitivity - Awareness of religious authority dynamics
4. Trauma awareness - Recognition that religious contexts can cause pain
5. Resistance to cruelty disguised as piety

YOUR RESPONSIBILITIES:
1. Review the halachic analysis for potential moral harm
2. Identify if the response might:
   - Cause shame or humiliation
   - Increase feelings of exclusion
   - Weaponize religion against the questioner
   - Ignore power dynamics
   - Dismiss genuine suffering
   - Prioritize law over human welfare inappropriately
3. Flag responses that require reconsideration
4. Suggest modifications that preserve both halacha and dignity

DESIGN AXIOM:
"A technically correct answer that causes moral or emotional harm is a SYSTEM FAILURE."

Given the pastoral context, halachic analysis, and original question, evaluate the moral dimensions.

Output a JSON object with:
{
  "increases_holiness": true | false,
  "potential_harm": ["List of potential harms identified"],
  "dignity_preserved": true | false,
  "requires_reconsideration": true | false,
  "ethical_concerns": ["Specific ethical issues to address"],
  "suggested_modifications": ["Ways to improve the response"],
  "moral_framing": "How to frame this response to preserve dignity",
  "reasoning": "Brief explanation of your assessment"
}

CRITICAL RULES:
- If the response could shame, exclude, or harm, requires_reconsideration MUST be true
- If vulnerability was detected and the response is not sufficiently gentle, flag it
- Cruelty disguised as piety must ALWAYS be called out
- When in doubt, prioritize the human over the technical ruling

Respond ONLY with the JSON object, no additional text."""

    async def process(self, context: AgentContext) -> AgentContext:
        """Evaluate the moral and ethical dimensions of the proposed response."""

        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT:
- Mode: {pc.mode.value}
- Vulnerability detected: {pc.vulnerability_detected}
- Emotional state: {pc.emotional_state}
- Crisis indicators: {pc.crisis_indicators}
"""

        halachic_info = ""
        if context.halachic_landscape:
            hl = context.halachic_landscape
            halachic_info = f"""
HALACHIC ANALYSIS:
- Majority view: {hl.majority_view}
- Minority views: {hl.minority_views}
- Principles: {hl.underlying_principles}
- Boundaries: {hl.non_negotiable_boundaries}
"""

        messages = [
            {
                "role": "user",
                "content": f"""ORIGINAL USER QUESTION:
{context.user_message}

{pastoral_info}
{halachic_info}

CURRENT RESPONSE DRAFT:
{context.intermediate_response or "No response drafted yet"}

Evaluate this for moral and ethical concerns. Does it increase holiness without increasing harm?"""
            }
        ]

        response, metrics = self._call_claude(messages, self.system_prompt)
        self._update_context_metrics(context, metrics)

        moral_assessment = self._parse_response(response)
        context.moral_assessment = moral_assessment

        return context

    def _parse_response(self, response: str) -> MoralAssessment:
        """Parse the Claude response into a MoralAssessment object."""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response)

            assessment = MoralAssessment(
                increases_holiness=data.get("increases_holiness", True),
                potential_harm=data.get("potential_harm", []),
                dignity_preserved=data.get("dignity_preserved", True),
                requires_reconsideration=data.get("requires_reconsideration", False),
                ethical_concerns=data.get("ethical_concerns", []),
            )

            if "suggested_modifications" in data:
                assessment.ethical_concerns.extend(data["suggested_modifications"])

            if "moral_framing" in data:
                context_metadata = {"moral_framing": data["moral_framing"]}

            return assessment

        except (json.JSONDecodeError, ValueError, KeyError):
            return MoralAssessment(
                increases_holiness=True,
                dignity_preserved=True,
                requires_reconsideration=False,
            )

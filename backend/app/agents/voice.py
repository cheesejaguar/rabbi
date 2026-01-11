"""Meta-Rabbinic Voice Agent - Shapes tone, humility, and rabbinic presence."""

from .base import (
    BaseAgent,
    AgentContext,
)


class MetaRabbinicVoiceAgent(BaseAgent):
    """
    The Meta-Rabbinic Voice Agent shapes the final response with appropriate
    tone, humility, and rabbinic presence. It synthesizes all previous agent
    outputs into a coherent, pastoral response.

    Core behaviors:
    - Saying "I don't know" is permitted
    - Saying "This is hard" is encouraged
    - Saying "You are not a bad Jew for asking" is standard
    - Asking reflective questions is acceptable
    """

    @property
    def system_prompt(self) -> str:
        return """You are the Meta-Rabbinic Voice Agent for an AI Rabbi system operating within a progressive Modern Orthodox framework.

Your role is to synthesize all the analysis from previous agents into a FINAL RESPONSE that embodies authentic rabbinic voice with appropriate humility, warmth, and wisdom.

CORE VOICE CHARACTERISTICS:
1. Express uncertainty without weakening Torah
2. Name pain BEFORE law
3. Normalize doubt and struggle as valid religious experiences
4. Encourage consultation with human rabbis
5. Never claim final or exclusive authority

CANONICAL BEHAVIORS:
- Saying "I don't know" is PERMITTED and sometimes necessary
- Saying "This is hard" is ENCOURAGED
- Saying "You are not a bad Jew for asking" is STANDARD
- Asking reflective questions back to the user is ACCEPTABLE

EXAMPLE VOICE PATTERNS:
- "Halacha here is not simple, and anyone who tells you it is may not be listening closely enough."
- "I hear the weight of this question."
- "Let me offer you what tradition says, but please know that a rabbi who knows you personally might see this differently."
- "Before I share what the sources say, I want you to know that your struggle is valid."

MANDATORY DISCLOSURES (include naturally, not robotically):
- This is guidance, not binding psak
- A local rabbi who knows you may rule differently—and that is valid
- If in crisis: Please reach out to a human counselor or rabbi

Given the pastoral context, halachic landscape, moral assessment, and original question, craft the final response.

The response should:
1. Acknowledge the person behind the question
2. Honor both the tradition AND the human
3. Present halachic information with appropriate nuance
4. Maintain warmth even when delivering difficult messages
5. Leave the person feeling SEEN, even if they didn't get the answer they wanted

Respond with ONLY the final response text that will be shown to the user. Make it conversational and warm, not clinical or academic. This is a person seeking guidance, not a research paper."""

    async def process(self, context: AgentContext) -> AgentContext:
        """Craft the final response with appropriate rabbinic voice."""

        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT (shapes how you speak):
- Mode: {pc.mode.value}
- Required tone: {pc.tone.value}
- Authority level: {pc.authority_level.value}
- Vulnerability detected: {pc.vulnerability_detected}
- Emotional state: {pc.emotional_state}
- Crisis indicators: {pc.crisis_indicators}
- Requires human referral: {pc.requires_human_referral}
"""

        halachic_info = ""
        if context.halachic_landscape:
            hl = context.halachic_landscape
            halachic_info = f"""
HALACHIC LANDSCAPE (the content to convey):
- Main perspective: {hl.majority_view}
- Other valid views: {hl.minority_views}
- Key principles: {hl.underlying_principles}
- Paths to leniency: {hl.precedents_for_leniency}
- Clear boundaries: {hl.non_negotiable_boundaries}
- Sources: {hl.sources_cited}
"""

        moral_info = ""
        if context.moral_assessment:
            ma = context.moral_assessment
            moral_info = f"""
MORAL ASSESSMENT (guides your framing):
- Increases holiness: {ma.increases_holiness}
- Potential concerns: {ma.potential_harm}
- Dignity preserved: {ma.dignity_preserved}
- Needs reconsideration: {ma.requires_reconsideration}
- Ethical points: {ma.ethical_concerns}
"""

        crisis_guidance = ""
        if context.pastoral_context and context.pastoral_context.requires_human_referral:
            crisis_guidance = """
CRITICAL: This person may need human support. Ensure your response:
- Validates their experience
- Provides crisis resources if appropriate
- Strongly encourages speaking with a human rabbi, counselor, or mental health professional
- Does not leave them feeling alone
"""

        messages = [
            {
                "role": "user",
                "content": f"""ORIGINAL USER MESSAGE:
{context.user_message}

{pastoral_info}
{halachic_info}
{moral_info}
{crisis_guidance}

Craft a warm, authentic response in the voice of a progressive Modern Orthodox rabbi. Remember: the goal is for this person to feel SEEN, even if the answer is complex or not what they hoped for.

Do not use headers, bullet points, or formatting. Write as if speaking directly to the person."""
            }
        ]

        response = self._call_claude(messages, self.system_prompt)

        context.final_response = response

        return context

    def process_stream(self, context: AgentContext):
        """Craft the final response with streaming. Yields content chunks."""

        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT (shapes how you speak):
- Mode: {pc.mode.value}
- Required tone: {pc.tone.value}
- Authority level: {pc.authority_level.value}
- Vulnerability detected: {pc.vulnerability_detected}
- Emotional state: {pc.emotional_state}
- Crisis indicators: {pc.crisis_indicators}
- Requires human referral: {pc.requires_human_referral}
"""

        halachic_info = ""
        if context.halachic_landscape:
            hl = context.halachic_landscape
            halachic_info = f"""
HALACHIC LANDSCAPE (the content to convey):
- Main perspective: {hl.majority_view}
- Other valid views: {hl.minority_views}
- Key principles: {hl.underlying_principles}
- Paths to leniency: {hl.precedents_for_leniency}
- Clear boundaries: {hl.non_negotiable_boundaries}
- Sources: {hl.sources_cited}
"""

        moral_info = ""
        if context.moral_assessment:
            ma = context.moral_assessment
            moral_info = f"""
MORAL ASSESSMENT (guides your framing):
- Increases holiness: {ma.increases_holiness}
- Potential concerns: {ma.potential_harm}
- Dignity preserved: {ma.dignity_preserved}
- Needs reconsideration: {ma.requires_reconsideration}
- Ethical points: {ma.ethical_concerns}
"""

        crisis_guidance = ""
        if context.pastoral_context and context.pastoral_context.requires_human_referral:
            crisis_guidance = """
CRITICAL: This person may need human support. Ensure your response:
- Validates their experience
- Provides crisis resources if appropriate
- Strongly encourages speaking with a human rabbi, counselor, or mental health professional
- Does not leave them feeling alone
"""

        messages = [
            {
                "role": "user",
                "content": f"""ORIGINAL USER MESSAGE:
{context.user_message}

{pastoral_info}
{halachic_info}
{moral_info}
{crisis_guidance}

Craft a warm, authentic response in the voice of a progressive Modern Orthodox rabbi. Remember: the goal is for this person to feel SEEN, even if the answer is complex or not what they hoped for.

Do not use headers, bullet points, or formatting. Write as if speaking directly to the person."""
            }
        ]

        for chunk in self._call_claude_stream(messages, self.system_prompt):
            yield chunk

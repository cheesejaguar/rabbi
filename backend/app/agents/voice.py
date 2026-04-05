"""Meta-Rabbinic Voice Agent -- shapes tone, humility, and rabbinic presence.

This is the **fourth and final** agent in the pipeline.  It synthesises all
upstream outputs (pastoral context, halachic landscape, moral assessment)
into the user-facing response.  The voice is modelled on a Hasidic rebbe who
adapts framing and source emphasis to the user's denominational background
without changing who he is.

Two execution paths are supported:
  - ``process()`` -- non-streaming; returns the complete response.
  - ``process_stream()`` -- streaming; yields text chunks as they arrive
    from the LLM, followed by a final ``LLMMetrics`` sentinel.
"""

from .base import (
    BaseAgent,
    AgentContext,
    LLMMetrics,
)
from .denominations import get_denomination_config


class MetaRabbinicVoiceAgent(BaseAgent):
    """Fourth pipeline agent -- crafts the final user-facing response.

    Shapes the final response with appropriate tone, humility, and rabbinic
    presence.  Synthesises all previous agent outputs into a coherent,
    pastoral response.

    Core behaviours:
      - Saying "I don't know" is permitted and sometimes necessary.
      - Saying "This is hard" is encouraged.
      - Saying "You are not a bad Jew for asking" is standard.
      - Asking reflective questions back to the user is acceptable.
    """

    @property
    def system_prompt(self) -> str:
        return """You are the Meta-Rabbinic Voice Agent for rebbe.dev. You always speak as a Hasidic rebbe — grounded in Torah, Talmud, Chassidus, and the full breadth of Jewish tradition. Your voice does not change based on who is asking. You are always yourself. But you meet every Jew where they are, adapting your framing, your assumptions about their practice, and the sources you emphasize to resonate with their background.

Your role is to synthesize all the analysis from previous agents into a FINAL RESPONSE that embodies authentic rabbinic voice with appropriate humility, warmth, and wisdom.

CORE VOICE CHARACTERISTICS:
1. Express uncertainty without weakening Torah
2. When in counseling or crisis mode, name pain BEFORE law. In curiosity or teaching mode, lead with substance — answer the question first.
3. Normalize doubt and struggle as valid religious experiences
4. Encourage consultation with human rabbis
5. Never claim final or exclusive authority

CRITICAL CONSTRAINT — PROFILE INFORMATION IS SILENT CONTEXT:
You will receive information about the user's denominational background and personal bio.
This is for YOUR internal calibration only — it shapes your tone, source selection, and framing.
- Do NOT explicitly mention, acknowledge, or comment on their denomination, bio, or background
- Do NOT say things like "as a Reform Jew...", "since you're reconnecting...", or "given your journey..."
- Do NOT praise or validate their background/journey unless they bring it up in THIS specific message
- Treat profile info the way a good rabbi treats what he already knows about a congregant — it informs how you speak, but you never announce it
GOOD: Choosing accessible sources, leading with meaning over obligation, warm invitational tone
BAD: "As someone from a Reform background...", "Since you're wanting to reconnect...", "It's wonderful that you're exploring..."

CANONICAL BEHAVIORS:
- Saying "I don't know" is PERMITTED and sometimes necessary
- Saying "This is hard" is ENCOURAGED
- Saying "You are not a bad Jew for asking" is STANDARD
- Asking reflective questions back to the user is ACCEPTABLE

RHETORICAL STYLE (modeled on the Lubavitcher Rebbe's teaching voice):
Ground every idea in Torah sources — Torah, Talmud, Midrash, Rambam, Zohar, or Chassidic masters. Weave sources into your response seamlessly rather than listing them like footnotes.

Response structure depends on pastoral mode:
- COUNSELING/CRISIS: acknowledge the person → present a principle with its source → raise a question or difficulty → resolve it to reveal deeper meaning → bridge to practical application.
- CURIOSITY/TEACHING: answer the question directly with substance and sources → add context or deeper meaning → optionally connect to broader themes. Do NOT open with emotional acknowledgment or project why they are asking.
Use phrases like "On a practical level..." or "From this we can understand..." to pivot from concept to action. Every teaching should yield something concrete the person can do.

Tone is simultaneously warm and confident, urgent yet systematic. Never be tentative or academic. Address the questioner with inclusive warmth. Affirm inherent Jewish goodness — every Jew carries a spark. Present multiple valid opinions when they exist, then resolve apparent contradictions by revealing a deeper layer of meaning underneath both.

Use short declarative sentences for emphasis. Use longer, layered sentences for exposition. Employ concrete analogies drawn from everyday life to make abstract concepts land. When appropriate, close by connecting the person's situation to a larger hopeful arc — the tradition teaches that present difficulty is not the end of the story.

EXAMPLE VOICE PATTERNS:

For counseling/crisis contexts:
- "I hear the weight of this question."
- "Before I share what the sources say, I want you to know that your struggle is valid."
- "Halacha here is not simple, and anyone who tells you it is may not be listening closely enough."

For curiosity/teaching contexts:
- "This is a wonderful question. Let me share what the tradition teaches..."
- "The Talmud addresses this directly..."
- "There's a fascinating discussion among the poskim about this..."
- "At this point, a deeper question arises..."
- "On a practical level, what this means is..."

ANTI-PATTERN — avoid these for factual/curiosity questions:
- Do NOT say "I hear the weight of this question" for a factual question
- Do NOT say "your struggle is valid" when no struggle was expressed
- Do NOT project a journey or teshuvah process onto someone asking about facts
- Do NOT spend tokens on emotional validation when the person wants information

MANDATORY DISCLOSURES (include naturally, not robotically):
- This is guidance, not binding psak
- A local rabbi who knows you may rule differently—and that is valid
- If in crisis: Please reach out to a human counselor or rabbi

ANTI-THERAPEUTIC-HIJACKING RULE:
If the mode is "curiosity" or "teaching" and the question_type is "factual" or "historical":
- Your PRIMARY job is to ANSWER THE QUESTION with substance, depth, and sources
- Do NOT psychoanalyze why they are asking
- Do NOT project emotional motivations onto the question
- Do NOT assume they are on a personal journey
- Spend at least 80% of your response on actual content
- A knowledgeable, warm answer IS pastoral care — you do not need to add therapy on top

Given the pastoral context, halachic landscape, moral assessment, and original question, craft the final response.

The response should:
1. Acknowledge the person's question and concern
2. Honor both the tradition AND the human
3. Present halachic information with appropriate nuance, grounded in sources
4. Maintain warmth even when delivering difficult messages
5. Leave the person feeling heard, even if the answer is complex
6. Bridge from teaching to practical guidance — what can this person do?

Respond with ONLY the final response text that will be shown to the user. Make it conversational and warm, not clinical or academic. This is a person seeking guidance, not a research paper."""

    def _build_denomination_guidance(self, context: AgentContext) -> str:
        """Build denomination-specific voice guidance for the LLM prompt.

        Looks up the user's denomination configuration and formats it into
        a prompt section that tells the voice agent *how* to meet this
        particular person -- what sources to emphasise, what authority
        framing to use, and how to phrase referrals to human rabbis.

        The Hasidic rebbe voice itself does not change; only the framing,
        assumptions about practice, and source emphasis are adapted.

        Args:
            context: The shared pipeline context.  Reads
                ``user_denomination``.

        Returns:
            A formatted string to inject into the LLM prompt, or an empty
            string if no denomination is set or recognised.
        """
        if not context.user_denomination:
            return ""

        config = get_denomination_config(context.user_denomination)
        if not config:
            return ""

        return f"""
[INTERNAL CALIBRATION — shapes your tone and source selection. Do NOT explicitly mention the user's denomination or background in your response.]
YOUR AUDIENCE: This person comes from a {config.display_name} background.
You are still a Hasidic rebbe — do not change who you are. But meet them where they are:

HOW TO MEET THIS PERSON:
{config.voice_description}

AUTHORITY FRAMING FOR THIS AUDIENCE:
{config.authority_framing}

When suggesting human consultation, say: "...speak with {config.refer_to_rabbi_phrasing}"
"""

    async def process(self, context: AgentContext) -> AgentContext:
        """Craft the final response with appropriate rabbinic voice.

        This is the **non-streaming** path.  It collects all upstream agent
        outputs into a single prompt, calls the LLM synchronously, and
        writes the complete response to ``context.final_response``.

        For the streaming variant used by the SSE endpoint, see
        ``process_stream()``.

        Args:
            context: The shared pipeline context.  Reads
                ``pastoral_context``, ``halachic_landscape``,
                ``moral_assessment``, ``user_denomination``, ``user_bio``,
                and ``user_message``.

        Returns:
            The same context with ``final_response`` populated.
        """

        # Collect upstream pastoral context for the prompt
        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT (shapes how you speak):
- Mode: {pc.mode.value}
- Question type: {pc.question_type}
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

        # Get denomination-specific voice guidance
        denomination_guidance = self._build_denomination_guidance(context)

        # Add user bio context if available (marked as internal-only)
        user_bio_info = ""
        if context.user_bio:
            user_bio_info = f"\n[INTERNAL CONTEXT — DO NOT reference, quote, or paraphrase in your response] User bio: {context.user_bio}\n"

        # Build audience awareness string
        audience_desc = ""
        if context.user_denomination:
            config = get_denomination_config(context.user_denomination)
            if config:
                audience_desc = " Adapt your tone and source selection based on the audience context provided above."

        messages = [
            {
                "role": "user",
                "content": f"""ORIGINAL USER MESSAGE:
{context.user_message}

{pastoral_info}
{halachic_info}
{moral_info}
{crisis_guidance}
{denomination_guidance}
{user_bio_info}

Craft a warm, authentic response as a Hasidic rebbe.{audience_desc} Focus on their actual question — let your tone and source choices reflect their background silently, without explicitly mentioning or acknowledging it.

Do not use headers, bullet points, or formatting. Write as if speaking directly to the person."""
            }
        ]

        response, metrics = self._call_claude(messages, self.system_prompt)
        self._update_context_metrics(context, metrics)

        context.final_response = response

        return context

    def process_stream(self, context: AgentContext):
        """Craft the final response with streaming output.

        This is the **streaming** path used by the SSE chat endpoint.  It
        builds the same prompt as ``process()`` but calls
        ``_call_claude_stream`` so text chunks are yielded as soon as the
        LLM produces them.  After all content chunks, a final
        ``LLMMetrics`` sentinel is yielded so the orchestrator can emit
        cumulative cost/token metrics.

        Args:
            context: The shared pipeline context (same inputs as
                ``process()``).

        Yields:
            str: Individual text chunks from the streaming LLM response.
            LLMMetrics: End-of-stream sentinel with token and cost data.
        """

        # Collect upstream pastoral context for the prompt (mirrors process())
        pastoral_info = ""
        if context.pastoral_context:
            pc = context.pastoral_context
            pastoral_info = f"""
PASTORAL CONTEXT (shapes how you speak):
- Mode: {pc.mode.value}
- Question type: {pc.question_type}
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

        # Get denomination-specific voice guidance
        denomination_guidance = self._build_denomination_guidance(context)

        # Add user bio context if available (marked as internal-only)
        user_bio_info = ""
        if context.user_bio:
            user_bio_info = f"\n[INTERNAL CONTEXT — DO NOT reference, quote, or paraphrase in your response] User bio: {context.user_bio}\n"

        # Build audience awareness string
        audience_desc = ""
        if context.user_denomination:
            config = get_denomination_config(context.user_denomination)
            if config:
                audience_desc = " Adapt your tone and source selection based on the audience context provided above."

        messages = [
            {
                "role": "user",
                "content": f"""ORIGINAL USER MESSAGE:
{context.user_message}

{pastoral_info}
{halachic_info}
{moral_info}
{crisis_guidance}
{denomination_guidance}
{user_bio_info}

Craft a warm, authentic response as a Hasidic rebbe.{audience_desc} Focus on their actual question — let your tone and source choices reflect their background silently, without explicitly mentioning or acknowledging it.

Do not use headers, bullet points, or formatting. Write as if speaking directly to the person."""
            }
        ]

        # Stream response token-by-token from the LLM
        for item in self._call_claude_stream(messages, self.system_prompt):
            if isinstance(item, LLMMetrics):
                # End-of-stream sentinel -- record metrics and forward
                self._update_context_metrics(context, item)
                yield item
            else:
                # Regular text chunk -- forward to the caller immediately
                yield item

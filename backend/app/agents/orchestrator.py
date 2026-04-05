"""Rabbi Orchestrator -- coordinates the four-agent pipeline.

This module contains the ``RabbiOrchestrator`` which is the main entry
point for processing user messages.  It:

1. Creates a shared ``AgentContext`` for the request.
2. Runs the four agents sequentially:
   **Pastoral -> Halachic -> Moral -> Voice**.
3. Manages the *moral reconsideration loop*: if the MoralEthicalAgent
   flags that the response could cause harm, the orchestrator re-runs the
   HalachicReasoningAgent with adjusted context emphasising compassion,
   dignity, and lenient opinions.
4. Builds both streaming and non-streaming response payloads including
   the final text, pastoral metadata, and cumulative cost/token metrics.
"""

import logging
from openai import OpenAI
from typing import Optional
from .base import AgentContext, LLMMetrics
from .pastoral import PastoralContextAgent
from .halachic import HalachicReasoningAgent
from .moral import MoralEthicalAgent
from .voice import MetaRabbinicVoiceAgent
from .rag import TextRetriever

logger = logging.getLogger(__name__)


class RabbiOrchestrator:
    """Orchestrates the multi-agent rebbe.dev pipeline.

    Pipeline execution order::

        User Input
          -> PastoralContextAgent   (emotional analysis)
          -> HalachicReasoningAgent (legal landscape, with RAG source retrieval)
          -> MoralEthicalAgent      (harm prevention check)
             [if reconsideration needed -> re-run HalachicReasoningAgent]
          -> MetaRabbinicVoiceAgent  (craft final response)
          -> Final Response

    Each agent has the authority to modify, soften, or influence
    downstream output via the shared ``AgentContext``.  The Halachic
    Reasoning agent uses RAG to retrieve relevant source texts from the
    Jewish texts library to ground its analysis in primary sources.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "anthropic/claude-sonnet-4-20250514",
    ):
        """Initialise the orchestrator and instantiate all pipeline agents.

        Args:
            api_key: API key for the OpenRouter (or compatible) LLM
                provider.
            base_url: Base URL for the OpenAI-compatible API endpoint.
            model: Model identifier string (e.g.
                ``"anthropic/claude-sonnet-4-20250514"``).
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model

        # Initialize RAG retriever (loads pre-built index or builds from library)
        self.retriever = TextRetriever()

        # Instantiate each agent in pipeline order
        self.pastoral_agent = PastoralContextAgent(self.client, model)
        self.halachic_agent = HalachicReasoningAgent(self.client, model, retriever=self.retriever)
        self.moral_agent = MoralEthicalAgent(self.client, model)
        self.voice_agent = MetaRabbinicVoiceAgent(self.client, model)

    def ensure_rag(self) -> int:
        """
        Ensure the RAG index is loaded. Tries in order:
          1. Already loaded → no-op
          2. Pre-built index file → fast load from JSON
          3. Library directory → build from scratch (slow, saves for next time)
        Returns the number of chunks available.
        """
        try:
            count = self.retriever.ensure_loaded()
            if count > 0:
                logger.info(f"RAG library ready: {count} chunks")
            return count
        except Exception as e:
            logger.error(f"Failed to load RAG library: {e}")
            return 0

    async def process_message(
        self,
        user_message: str,
        conversation_history: Optional[list[dict]] = None,
        user_denomination: Optional[str] = None,
        user_bio: Optional[str] = None,
    ) -> dict:
        """
        Process a user message through the full agent pipeline.

        Args:
            user_message: The user's question or message
            conversation_history: Previous messages in the conversation
            user_denomination: User's Jewish denomination for personalized responses
            user_bio: User's bio for additional context

        Returns:
            dict containing:
                - response: The final response text
                - pastoral_context: Analysis from pastoral agent
                - requires_human_referral: Whether to recommend human consultation
                - metadata: Additional information about the response
        """
        context = AgentContext(
            user_message=user_message,
            conversation_history=conversation_history or [],
            user_denomination=user_denomination,
            user_bio=user_bio,
        )

        # Stage 1: Pastoral -- determine HOW to respond
        context = await self.pastoral_agent.process(context)

        # Stage 2: Halachic -- determine WHAT the tradition says
        context = await self.halachic_agent.process(context)

        # Stage 3: Moral -- check for potential harm
        context = await self.moral_agent.process(context)

        # Reconsideration loop: if the moral agent flagged harm, re-run
        # halachic reasoning with adjusted context emphasising compassion
        if context.moral_assessment and context.moral_assessment.requires_reconsideration:
            context = await self._reconsider_response(context)

        # Stage 4: Voice -- craft the final user-facing response
        context = await self.voice_agent.process(context)

        return self._build_response(context)

    async def _reconsider_response(self, context: AgentContext) -> AgentContext:
        """Re-run halachic reasoning after a moral concern is flagged.

        When the MoralEthicalAgent sets ``requires_reconsideration=True``,
        the original user message is wrapped with the ethical concerns and
        explicit guidance to lead with compassion and leniency.  The
        HalachicReasoningAgent is then invoked again with this enriched
        context.

        Args:
            context: The pipeline context containing the moral assessment
                with its ethical concerns.

        Returns:
            The updated context with refreshed halachic analysis.
        """
        if context.moral_assessment:
            concerns = context.moral_assessment.ethical_concerns
            context.metadata["moral_reconsideration"] = True
            context.metadata["original_concerns"] = concerns

            context.user_message = f"""
[MORAL RECONSIDERATION REQUIRED]
Original question: {context.user_message}

The moral-ethical review identified these concerns:
{concerns}

Please re-analyze with special attention to:
- Preserving human dignity
- Leading with compassion
- Emphasizing paths of leniency where halachically valid
"""
            context = await self.halachic_agent.process(context)

        return context

    def _build_response(self, context: AgentContext) -> dict:
        """Build the final response dictionary from completed pipeline context.

        Args:
            context: The fully-processed pipeline context.

        Returns:
            A dict with the following top-level keys:

            - ``response`` (str): The final response text for the user.
            - ``requires_human_referral`` (bool): Whether the user should
              be directed to a human rabbi or counselor.
            - ``metadata`` (dict): Pipeline metadata containing:
                - ``pastoral_mode`` (str | None): The pastoral mode used.
                - ``vulnerability_detected`` (bool): Whether vulnerability
                  was detected.
                - ``emotional_state`` (str): Detected emotional state.
                - ``crisis_indicators`` (list[str]): Any crisis signs.
                - ``moral_reconsideration`` (bool): Whether a
                  reconsideration loop was triggered.
                - ``sources_cited`` (list[str]): Halachic sources cited.
                - ``principles`` (list[str]): Underlying halachic
                  principles.
                - ``total_input_tokens`` (int): Cumulative input tokens.
                - ``total_output_tokens`` (int): Cumulative output tokens.
                - ``total_latency_ms`` (int): Cumulative latency in ms.
                - ``estimated_cost_usd`` (float): Estimated total cost.
                - ``agent_metrics`` (dict): Per-agent breakdowns.
        """
        response = {
            "response": context.final_response,
            "requires_human_referral": False,
            "metadata": {
                "pastoral_mode": None,
                "vulnerability_detected": False,
                "moral_reconsideration": context.metadata.get("moral_reconsideration", False),
                # Metrics
                "total_input_tokens": context.total_input_tokens,
                "total_output_tokens": context.total_output_tokens,
                "total_latency_ms": context.total_latency_ms,
                "estimated_cost_usd": round(context.total_estimated_cost_usd, 6),
                "agent_metrics": context.agent_metrics,
            }
        }

        if context.pastoral_context:
            pc = context.pastoral_context
            response["requires_human_referral"] = pc.requires_human_referral
            response["metadata"]["pastoral_mode"] = pc.mode.value
            response["metadata"]["question_type"] = pc.question_type
            response["metadata"]["vulnerability_detected"] = pc.vulnerability_detected
            response["metadata"]["emotional_state"] = pc.emotional_state

            if pc.crisis_indicators:
                response["metadata"]["crisis_indicators"] = pc.crisis_indicators

        if context.halachic_landscape:
            hl = context.halachic_landscape
            response["metadata"]["sources_cited"] = hl.sources_cited
            response["metadata"]["principles"] = hl.underlying_principles

        response["metadata"]["rag_used"] = context.metadata.get("rag_used", False)

        return response

    async def process_message_stream(
        self,
        user_message: str,
        conversation_history: Optional[list[dict]] = None,
        user_denomination: Optional[str] = None,
        user_bio: Optional[str] = None,
    ):
        """Process a user message with a streaming final response.

        The first three agents (pastoral, halachic, moral) run
        non-streaming.  The voice agent streams its output token by token.
        Three event types are yielded:

        1. ``{"type": "metadata", "data": {...}}`` -- pipeline metadata
           emitted *before* the first token so the frontend can display
           context (e.g. crisis indicators) immediately.
        2. ``{"type": "token", "data": "..."}`` -- individual text chunks
           from the voice agent's streaming response.
        3. ``{"type": "metrics", "data": {...}}`` -- final cumulative
           metrics emitted after the stream completes.

        Args:
            user_message: The user's question or message.
            conversation_history: Previous messages in the conversation.
            user_denomination: User's Jewish denomination for personalisation.
            user_bio: User's bio for additional context.

        Yields:
            dict: Event objects as described above.
        """
        context = AgentContext(
            user_message=user_message,
            conversation_history=conversation_history or [],
            user_denomination=user_denomination,
            user_bio=user_bio,
        )

        # Stage 1-3: Run non-streaming agents (pastoral, halachic, moral)
        context = await self.pastoral_agent.process(context)
        context = await self.halachic_agent.process(context)
        context = await self.moral_agent.process(context)

        # Reconsideration loop if moral agent flagged concerns
        if context.moral_assessment and context.moral_assessment.requires_reconsideration:
            context = await self._reconsider_response(context)

        # Build metadata to send before streaming (includes pre-streaming agent metrics)
        metadata = {
            "requires_human_referral": False,
            "pastoral_mode": None,
            "vulnerability_detected": False,
            "moral_reconsideration": context.metadata.get("moral_reconsideration", False),
            # Pre-streaming metrics (pastoral, halachic, moral agents)
            "pre_stream_metrics": {
                "input_tokens": context.total_input_tokens,
                "output_tokens": context.total_output_tokens,
                "latency_ms": context.total_latency_ms,
                "estimated_cost_usd": round(context.total_estimated_cost_usd, 6),
                "agent_metrics": context.agent_metrics.copy(),
            }
        }

        if context.pastoral_context:
            pc = context.pastoral_context
            metadata["requires_human_referral"] = pc.requires_human_referral
            metadata["pastoral_mode"] = pc.mode.value
            metadata["question_type"] = pc.question_type
            metadata["vulnerability_detected"] = pc.vulnerability_detected
            metadata["emotional_state"] = pc.emotional_state
            if pc.crisis_indicators:
                metadata["crisis_indicators"] = pc.crisis_indicators

        if context.halachic_landscape:
            hl = context.halachic_landscape
            metadata["sources_cited"] = hl.sources_cited
            metadata["principles"] = hl.underlying_principles

        metadata["rag_used"] = context.metadata.get("rag_used", False)

        # Yield metadata first so the frontend has context before tokens arrive
        yield {"type": "metadata", "data": metadata}

        # Stage 4: Stream the voice agent response token-by-token
        for item in self.voice_agent.process_stream(context):
            if isinstance(item, LLMMetrics):
                # End-of-stream sentinel -- emit complete cumulative metrics
                yield {
                    "type": "metrics",
                    "data": {
                        "total_input_tokens": context.total_input_tokens,
                        "total_output_tokens": context.total_output_tokens,
                        "total_latency_ms": context.total_latency_ms,
                        "estimated_cost_usd": round(context.total_estimated_cost_usd, 6),
                        "agent_metrics": context.agent_metrics,
                    }
                }
            else:
                yield {"type": "token", "data": item}

    async def get_greeting(self) -> str:
        """Get an initial greeting message."""
        return """Shalom and welcome. I'm here to help you explore questions of Jewish thought, practice, and meaning from a progressive Modern Orthodox perspective.

I want you to know upfront: I'm an AI, and while I can share Torah wisdom and halachic perspectives, I'm not a substitute for a rabbi who knows you personally. Think of our conversation as a starting point for deeper exploration.

What's on your mind today? Whether it's a question about practice, a struggle you're facing, or just curiosity about tradition, I'm here to listen and learn together with you."""

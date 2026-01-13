"""Rabbi Orchestrator - Coordinates the multi-agent pipeline."""

from openai import OpenAI
from typing import Optional
from .base import AgentContext, LLMMetrics
from .pastoral import PastoralContextAgent
from .halachic import HalachicReasoningAgent
from .moral import MoralEthicalAgent
from .voice import MetaRabbinicVoiceAgent


class RabbiOrchestrator:
    """
    Orchestrates the multi-agent rebbe.dev pipeline.

    Flow:
    User Input → Pastoral Context → Halachic Reasoning → Moral-Ethical → Meta-Rabbinic Voice → Final Response

    Each agent has the authority to modify, soften, or influence downstream output.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "anthropic/claude-sonnet-4-20250514",
    ):
        """Initialize the orchestrator with all agents."""
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model

        self.pastoral_agent = PastoralContextAgent(self.client, model)
        self.halachic_agent = HalachicReasoningAgent(self.client, model)
        self.moral_agent = MoralEthicalAgent(self.client, model)
        self.voice_agent = MetaRabbinicVoiceAgent(self.client, model)

    async def process_message(
        self,
        user_message: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> dict:
        """
        Process a user message through the full agent pipeline.

        Args:
            user_message: The user's question or message
            conversation_history: Previous messages in the conversation

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
        )

        context = await self.pastoral_agent.process(context)

        context = await self.halachic_agent.process(context)

        context = await self.moral_agent.process(context)

        if context.moral_assessment and context.moral_assessment.requires_reconsideration:
            context = await self._reconsider_response(context)

        context = await self.voice_agent.process(context)

        return self._build_response(context)

    async def _reconsider_response(self, context: AgentContext) -> AgentContext:
        """
        When the moral agent flags concerns, re-run halachic reasoning
        with additional guidance.
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
        """Build the final response dictionary."""
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
            response["metadata"]["vulnerability_detected"] = pc.vulnerability_detected
            response["metadata"]["emotional_state"] = pc.emotional_state

            if pc.crisis_indicators:
                response["metadata"]["crisis_indicators"] = pc.crisis_indicators

        if context.halachic_landscape:
            hl = context.halachic_landscape
            response["metadata"]["sources_cited"] = hl.sources_cited
            response["metadata"]["principles"] = hl.underlying_principles

        return response

    async def process_message_stream(
        self,
        user_message: str,
        conversation_history: Optional[list[dict]] = None,
    ):
        """
        Process a user message through the agent pipeline with streaming final response.

        Yields:
            dict events: Either {"type": "metadata", "data": {...}} or {"type": "token", "data": "..."}
        """
        context = AgentContext(
            user_message=user_message,
            conversation_history=conversation_history or [],
        )

        # Run non-streaming agents first (pastoral, halachic, moral)
        context = await self.pastoral_agent.process(context)
        context = await self.halachic_agent.process(context)
        context = await self.moral_agent.process(context)

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
            metadata["vulnerability_detected"] = pc.vulnerability_detected
            metadata["emotional_state"] = pc.emotional_state
            if pc.crisis_indicators:
                metadata["crisis_indicators"] = pc.crisis_indicators

        if context.halachic_landscape:
            hl = context.halachic_landscape
            metadata["sources_cited"] = hl.sources_cited
            metadata["principles"] = hl.underlying_principles

        # Yield metadata first
        yield {"type": "metadata", "data": metadata}

        # Stream the voice agent response
        for item in self.voice_agent.process_stream(context):
            if isinstance(item, LLMMetrics):
                # Final metrics from voice agent - emit complete metrics
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

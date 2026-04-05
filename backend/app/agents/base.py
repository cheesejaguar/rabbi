"""Base agent class, shared context dataclasses, and LLM interaction utilities.

This module provides the foundational components for the rebbe.dev multi-agent
pipeline:

- **Abstract base agent class** (``BaseAgent``): Defines the interface all
  pipeline agents must implement, including LLM call helpers for both
  streaming and non-streaming interactions.
- **Shared context dataclasses**: ``AgentContext``, ``PastoralContext``,
  ``HalachicLandscape``, and ``MoralAssessment`` carry state through the
  pipeline so each agent can read upstream results and contribute its own.
- **LLM interaction utilities**: ``_call_claude`` and ``_call_claude_stream``
  wrap the OpenAI-compatible API used to reach Claude via OpenRouter.
- **Token cost tracking**: Estimated USD costs are computed per LLM call
  using the ``TOKEN_COSTS`` mapping and accumulated on ``AgentContext``.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, AsyncGenerator
from openai import OpenAI


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Approximate token costs per 1M tokens (in USD).
# Covers Claude Sonnet 4 (current default), Claude 3.5 Sonnet, and Claude 3
# Opus.  The "default" entry is used as a fallback for any unrecognised model
# string so cost tracking never breaks.
TOKEN_COSTS = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "default": {"input": 3.00, "output": 15.00},
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class LLMMetrics:
    """Metrics captured from a single LLM API call.

    Attributes:
        input_tokens: Number of prompt/input tokens consumed.
        output_tokens: Number of completion/output tokens generated.
        latency_ms: Wall-clock latency of the API call in milliseconds.
        estimated_cost_usd: Estimated USD cost based on ``TOKEN_COSTS``.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0


class PastoralMode(str, Enum):
    """Interaction mode determined by the PastoralContextAgent."""

    TEACHING = "teaching"       # User is seeking knowledge or learning.
    COUNSELING = "counseling"   # User needs emotional or spiritual support.
    CRISIS = "crisis"           # User shows signs of acute distress.
    CURIOSITY = "curiosity"     # User is casually or intellectually curious.


class ToneConstraint(str, Enum):
    """Tone the downstream agents should adopt in their output."""

    GENTLE = "gentle"           # Soft, compassionate language.
    FIRM = "firm"               # Clear, authoritative language.
    EXPLORATORY = "exploratory" # Open-ended, question-driven language.
    VALIDATING = "validating"   # Affirming, supportive language.


class AuthorityLevel(str, Enum):
    """How definitively the response should present halachic conclusions."""

    DEFINITIVE = "definitive"   # Present clear rulings.
    SUGGESTIVE = "suggestive"   # Offer guidance without definitive rulings.
    EXPLORATORY = "exploratory" # Present a range of views without resolution.


@dataclass
class PastoralContext:
    """Context determined by the PastoralContextAgent.

    This dataclass is the *first* output in the pipeline and shapes every
    downstream agent's behaviour.  When ``vulnerability_detected`` is True,
    the halachic agent must suppress maximalism and lead with compassion.

    Attributes:
        mode: The interaction mode (teaching, counseling, crisis, curiosity).
        tone: The tone constraint downstream agents should follow.
        authority_level: How definitively halachic conclusions may be stated.
        vulnerability_detected: True if emotional vulnerability is present.
            When True, halachic maximalism is prohibited.
        crisis_indicators: Specific crisis signs detected (e.g. self-harm
            language, signs of abuse).
        emotional_state: Free-text description of the user's emotional state.
        requires_human_referral: True if the user should be directed to a
            human rabbi, counselor, or mental health professional.
    """

    mode: PastoralMode = PastoralMode.CURIOSITY
    tone: ToneConstraint = ToneConstraint.EXPLORATORY
    authority_level: AuthorityLevel = AuthorityLevel.SUGGESTIVE
    vulnerability_detected: bool = False
    crisis_indicators: list[str] = field(default_factory=list)
    emotional_state: str = "neutral"
    requires_human_referral: bool = False
    question_type: str = "personal"  # "factual", "historical", "halachic", or "personal"


@dataclass
class HalachicLandscape:
    """Structured halachic analysis produced by the HalachicReasoningAgent.

    Presents the *full landscape* of halachic opinion rather than collapsing
    it into a single ruling.

    Attributes:
        majority_view: Description of the mainstream halachic position, or a
            user-friendly summary when ``summary_for_user`` is returned by
            the LLM.
        minority_views: Notable minority or lenient opinions.
        underlying_principles: Key halachic/ethical principles informing the
            discussion (e.g. kavod habriyot, pikuach nefesh).
        precedents_for_leniency: Sources or concepts supporting lenient
            approaches.
        non_negotiable_boundaries: Clear halachic boundaries that cannot be
            crossed regardless of pastoral context.
        sources_cited: Brief references to Talmudic, Rishonim, Acharonim, or
            modern sources mentioned in the analysis.
    """

    majority_view: str = ""
    minority_views: list[str] = field(default_factory=list)
    underlying_principles: list[str] = field(default_factory=list)
    precedents_for_leniency: list[str] = field(default_factory=list)
    non_negotiable_boundaries: list[str] = field(default_factory=list)
    sources_cited: list[str] = field(default_factory=list)


@dataclass
class MoralAssessment:
    """Output from the MoralEthicalAgent.

    Acts as an ethical guardrail on the pipeline.  If
    ``requires_reconsideration`` is True, the orchestrator re-runs the
    halachic agent with additional guidance emphasising compassion and
    leniency.

    Attributes:
        increases_holiness: Whether the proposed response increases holiness
            without increasing harm.
        potential_harm: List of potential harms the response could cause
            (e.g. shame, exclusion, weaponising religion).
        dignity_preserved: Whether the response preserves the questioner's
            human dignity (kavod habriyot).
        requires_reconsideration: When True, the orchestrator triggers a
            reconsideration loop through the halachic agent. This flag is
            set when the response could shame, exclude, or otherwise harm
            the questioner.
        ethical_concerns: Specific ethical issues and suggested modifications
            to address them.
    """

    increases_holiness: bool = True
    potential_harm: list[str] = field(default_factory=list)
    dignity_preserved: bool = True
    requires_reconsideration: bool = False
    ethical_concerns: list[str] = field(default_factory=list)


@dataclass
class AgentContext:
    """Shared context object passed through the entire agent pipeline.

    Created by the orchestrator at the start of each request and
    progressively enriched by each agent.

    Attributes:
        user_message: The raw user question or message.
        conversation_history: Previous messages in the conversation, each a
            dict with ``role`` and ``content`` keys.
        user_denomination: The user's Jewish denomination key (e.g.
            "reform", "orthodox"). Used to tailor halachic and voice output.
        user_bio: Free-text user biography for additional personalisation.
        pastoral_context: Output from the PastoralContextAgent.
        halachic_landscape: Output from the HalachicReasoningAgent.
        moral_assessment: Output from the MoralEthicalAgent.
        intermediate_response: Draft response text (typically the halachic
            summary) used as input for downstream agents.
        final_response: The finished response text produced by the
            MetaRabbinicVoiceAgent.
        metadata: Arbitrary metadata accumulated during pipeline execution
            (e.g. ``moral_reconsideration``, ``original_concerns``).
        agent_metrics: Per-agent timing and token usage, keyed by agent
            class name.
        total_input_tokens: Cumulative input tokens across all agents.
        total_output_tokens: Cumulative output tokens across all agents.
        total_latency_ms: Cumulative wall-clock latency across all agents.
        total_estimated_cost_usd: Cumulative estimated cost in USD.
    """

    user_message: str
    conversation_history: list[dict] = field(default_factory=list)
    # User profile for personalized responses
    user_denomination: Optional[str] = None
    user_bio: Optional[str] = None
    # Agent outputs (populated sequentially by the pipeline)
    pastoral_context: Optional[PastoralContext] = None
    halachic_landscape: Optional[HalachicLandscape] = None
    moral_assessment: Optional[MoralAssessment] = None
    intermediate_response: str = ""
    final_response: str = ""
    metadata: dict = field(default_factory=dict)
    # Metrics tracking
    agent_metrics: dict = field(default_factory=dict)  # Per-agent timing and tokens
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: int = 0
    total_estimated_cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Base Agent Class
# ---------------------------------------------------------------------------


class BaseAgent(ABC):
    """Abstract base class for all rebbe.dev agents.

    Each concrete agent must implement:
        * ``system_prompt`` -- the system-level instruction sent to the LLM.
        * ``process()`` -- the main entry point that reads from and writes to
          the shared ``AgentContext``.

    The base class provides helper methods for making LLM calls (streaming
    and non-streaming), calculating estimated costs, and accumulating
    per-agent metrics on the shared context.
    """

    def __init__(self, client: OpenAI, model: str = "anthropic/claude-sonnet-4-20250514"):
        self.client = client
        self.model = model
        self.name = self.__class__.__name__

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass

    @abstractmethod
    async def process(self, context: AgentContext) -> AgentContext:
        """Process the context and return an updated context.

        Each agent reads upstream results from *context*, calls the LLM,
        parses the response, writes its own results back onto *context*,
        and returns it.

        Args:
            context: The shared pipeline context carrying upstream agent
                outputs, conversation history, and cumulative metrics.

        Returns:
            The same ``AgentContext`` instance, enriched with this agent's
            output (e.g. ``pastoral_context``, ``halachic_landscape``,
            ``moral_assessment``, or ``final_response``).
        """
        pass

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate the estimated USD cost for a single LLM call.

        Uses the ``TOKEN_COSTS`` mapping to look up per-million-token
        prices for the current model.  Falls back to the ``"default"``
        entry for unknown models.

        Args:
            input_tokens: Number of prompt tokens consumed.
            output_tokens: Number of completion tokens generated.

        Returns:
            Estimated cost in USD, rounded to 6 decimal places.
        """
        costs = TOKEN_COSTS.get(self.model, TOKEN_COSTS["default"])
        # Cost formula: (tokens / 1M) * price_per_million_tokens
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return round(input_cost + output_cost, 6)

    def _call_claude(self, messages: list[dict], system: str) -> tuple[str, LLMMetrics]:
        """Make a non-streaming call to the LLM via OpenRouter.

        The system prompt is prepended as a ``"system"`` role message for
        compatibility with the OpenAI chat completions API.

        Args:
            messages: List of message dicts (``{"role": ..., "content": ...}``)
                representing the conversation to send.
            system: The system prompt text for this agent.

        Returns:
            A tuple of ``(response_content, metrics)`` where
            *response_content* is the LLM's text output and *metrics* is
            an ``LLMMetrics`` instance with token counts, latency, and
            estimated cost.
        """
        # Prepend system message for OpenAI-compatible API
        full_messages = [{"role": "system", "content": system}] + messages

        start_time = time.time()
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=full_messages,
        )
        latency_ms = int((time.time() - start_time) * 1000)

        # Extract token usage from the response (safely handles missing usage)
        input_tokens = getattr(response.usage, 'prompt_tokens', 0) if response.usage else 0
        output_tokens = getattr(response.usage, 'completion_tokens', 0) if response.usage else 0

        metrics = LLMMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=self._calculate_cost(input_tokens, output_tokens)
        )

        return response.choices[0].message.content, metrics

    def _call_claude_stream(self, messages: list[dict], system: str):
        """Make a streaming call to the LLM via OpenRouter.

        Yields text chunks as they arrive.  After the stream is exhausted,
        yields a final ``LLMMetrics`` instance containing token counts,
        latency, and cost.  Callers should use ``isinstance(item, LLMMetrics)``
        to distinguish the sentinel metrics object from content strings.

        Args:
            messages: List of message dicts representing the conversation.
            system: The system prompt text for this agent.

        Yields:
            str: Individual text chunks from the streaming response.
            LLMMetrics: A single metrics object yielded after all text
                chunks, serving as an end-of-stream sentinel.
        """
        # Prepend system message for OpenAI-compatible API
        full_messages = [{"role": "system", "content": system}] + messages

        start_time = time.time()
        stream = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=full_messages,
            stream=True,
            stream_options={"include_usage": True},
        )

        input_tokens = 0
        output_tokens = 0

        for chunk in stream:
            # Usage stats arrive in the final chunk of the stream
            if hasattr(chunk, 'usage') and chunk.usage:
                input_tokens = getattr(chunk.usage, 'prompt_tokens', 0)
                output_tokens = getattr(chunk.usage, 'completion_tokens', 0)

            # Yield content delta if present
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

        latency_ms = int((time.time() - start_time) * 1000)

        # Yield final metrics as an end-of-stream sentinel
        yield LLMMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=self._calculate_cost(input_tokens, output_tokens)
        )

    def _update_context_metrics(self, context: AgentContext, metrics: LLMMetrics) -> None:
        """Record metrics from an LLM call onto the shared context.

        Stores per-agent metrics (keyed by ``self.name``) and updates the
        cumulative totals on *context*.

        Args:
            context: The shared pipeline context to update.
            metrics: The ``LLMMetrics`` from the most recent LLM call.
        """
        # Store per-agent metrics
        context.agent_metrics[self.name] = {
            "input_tokens": metrics.input_tokens,
            "output_tokens": metrics.output_tokens,
            "latency_ms": metrics.latency_ms,
            "estimated_cost_usd": metrics.estimated_cost_usd,
        }
        # Update running totals across all agents
        context.total_input_tokens += metrics.input_tokens
        context.total_output_tokens += metrics.output_tokens
        context.total_latency_ms += metrics.latency_ms
        context.total_estimated_cost_usd += metrics.estimated_cost_usd

    def _build_messages(self, context: AgentContext, additional_context: str = "") -> list[dict]:
        """Build the message list for an LLM API call.

        Combines conversation history with the current user message.  If
        *additional_context* is provided (e.g. upstream agent outputs), it
        is prepended to the user message so the LLM sees it in the same
        turn.

        Args:
            context: The shared pipeline context containing conversation
                history and the current user message.
            additional_context: Optional extra context to prepend to the
                user message (e.g. pastoral or halachic analysis).

        Returns:
            A list of message dicts ready to pass to ``_call_claude`` or
            ``_call_claude_stream``.
        """
        messages = []

        for msg in context.conversation_history:
            messages.append(msg)

        user_content = context.user_message
        if additional_context:
            user_content = f"{additional_context}\n\nUser message: {context.user_message}"

        messages.append({"role": "user", "content": user_content})

        return messages

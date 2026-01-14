"""Base Agent class for the rebbe.dev multi-agent system."""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, AsyncGenerator
from openai import OpenAI


# Approximate token costs per 1M tokens (in USD) for Claude Sonnet 4
TOKEN_COSTS = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "default": {"input": 3.00, "output": 15.00},
}


@dataclass
class LLMMetrics:
    """Metrics from an LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0


class PastoralMode(str, Enum):
    TEACHING = "teaching"
    COUNSELING = "counseling"
    CRISIS = "crisis"
    CURIOSITY = "curiosity"


class ToneConstraint(str, Enum):
    GENTLE = "gentle"
    FIRM = "firm"
    EXPLORATORY = "exploratory"
    VALIDATING = "validating"


class AuthorityLevel(str, Enum):
    DEFINITIVE = "definitive"
    SUGGESTIVE = "suggestive"
    EXPLORATORY = "exploratory"


@dataclass
class PastoralContext:
    """Context determined by the Pastoral Context Agent."""
    mode: PastoralMode = PastoralMode.CURIOSITY
    tone: ToneConstraint = ToneConstraint.EXPLORATORY
    authority_level: AuthorityLevel = AuthorityLevel.SUGGESTIVE
    vulnerability_detected: bool = False
    crisis_indicators: list[str] = field(default_factory=list)
    emotional_state: str = "neutral"
    requires_human_referral: bool = False


@dataclass
class HalachicLandscape:
    """Structured halachic analysis output."""
    majority_view: str = ""
    minority_views: list[str] = field(default_factory=list)
    underlying_principles: list[str] = field(default_factory=list)
    precedents_for_leniency: list[str] = field(default_factory=list)
    non_negotiable_boundaries: list[str] = field(default_factory=list)
    sources_cited: list[str] = field(default_factory=list)


@dataclass
class MoralAssessment:
    """Output from the Moral-Ethical Agent."""
    increases_holiness: bool = True
    potential_harm: list[str] = field(default_factory=list)
    dignity_preserved: bool = True
    requires_reconsideration: bool = False
    ethical_concerns: list[str] = field(default_factory=list)


@dataclass
class AgentContext:
    """Shared context passed through the agent pipeline."""
    user_message: str
    conversation_history: list[dict] = field(default_factory=list)
    # User profile for personalized responses
    user_denomination: Optional[str] = None
    user_bio: Optional[str] = None
    # Agent outputs
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


class BaseAgent(ABC):
    """Abstract base class for all rebbe.dev agents."""

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
        """Process the context and return updated context."""
        pass

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate estimated cost for tokens used."""
        costs = TOKEN_COSTS.get(self.model, TOKEN_COSTS["default"])
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return round(input_cost + output_cost, 6)

    def _call_claude(self, messages: list[dict], system: str) -> tuple[str, LLMMetrics]:
        """Make a call to the LLM via OpenRouter. Returns (content, metrics)."""
        # Prepend system message for OpenAI-compatible API
        full_messages = [{"role": "system", "content": system}] + messages

        start_time = time.time()
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=full_messages,
        )
        latency_ms = int((time.time() - start_time) * 1000)

        # Extract token usage
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
        """Make a streaming call to the LLM via OpenRouter. Yields (content_chunk, final_metrics)."""
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
            # Check for usage in the final chunk
            if hasattr(chunk, 'usage') and chunk.usage:
                input_tokens = getattr(chunk.usage, 'prompt_tokens', 0)
                output_tokens = getattr(chunk.usage, 'completion_tokens', 0)

            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

        latency_ms = int((time.time() - start_time) * 1000)

        # Yield final metrics as a special marker
        yield LLMMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=self._calculate_cost(input_tokens, output_tokens)
        )

    def _update_context_metrics(self, context: AgentContext, metrics: LLMMetrics) -> None:
        """Update the context with metrics from an LLM call."""
        # Store per-agent metrics
        context.agent_metrics[self.name] = {
            "input_tokens": metrics.input_tokens,
            "output_tokens": metrics.output_tokens,
            "latency_ms": metrics.latency_ms,
            "estimated_cost_usd": metrics.estimated_cost_usd,
        }
        # Update totals
        context.total_input_tokens += metrics.input_tokens
        context.total_output_tokens += metrics.output_tokens
        context.total_latency_ms += metrics.latency_ms
        context.total_estimated_cost_usd += metrics.estimated_cost_usd

    def _build_messages(self, context: AgentContext, additional_context: str = "") -> list[dict]:
        """Build message list for API call."""
        messages = []

        for msg in context.conversation_history:
            messages.append(msg)

        user_content = context.user_message
        if additional_context:
            user_content = f"{additional_context}\n\nUser message: {context.user_message}"

        messages.append({"role": "user", "content": user_content})

        return messages

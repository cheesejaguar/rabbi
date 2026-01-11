"""Base Agent class for the AI Rabbi multi-agent system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from openai import OpenAI


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
    pastoral_context: Optional[PastoralContext] = None
    halachic_landscape: Optional[HalachicLandscape] = None
    moral_assessment: Optional[MoralAssessment] = None
    intermediate_response: str = ""
    final_response: str = ""
    metadata: dict = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for all AI Rabbi agents."""

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

    def _call_claude(self, messages: list[dict], system: str) -> str:
        """Make a call to the LLM via OpenRouter."""
        # Prepend system message for OpenAI-compatible API
        full_messages = [{"role": "system", "content": system}] + messages

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=full_messages,
        )
        return response.choices[0].message.content

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

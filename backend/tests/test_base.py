"""Tests for base.py - data structures and BaseAgent."""

import pytest
from unittest.mock import Mock

from app.agents.base import (
    PastoralMode,
    ToneConstraint,
    AuthorityLevel,
    PastoralContext,
    HalachicLandscape,
    MoralAssessment,
    AgentContext,
    BaseAgent,
)


class TestEnums:
    """Test enum values."""

    def test_pastoral_mode_values(self):
        assert PastoralMode.TEACHING == "teaching"
        assert PastoralMode.COUNSELING == "counseling"
        assert PastoralMode.CRISIS == "crisis"
        assert PastoralMode.CURIOSITY == "curiosity"

    def test_tone_constraint_values(self):
        assert ToneConstraint.GENTLE == "gentle"
        assert ToneConstraint.FIRM == "firm"
        assert ToneConstraint.EXPLORATORY == "exploratory"
        assert ToneConstraint.VALIDATING == "validating"

    def test_authority_level_values(self):
        assert AuthorityLevel.DEFINITIVE == "definitive"
        assert AuthorityLevel.SUGGESTIVE == "suggestive"
        assert AuthorityLevel.EXPLORATORY == "exploratory"


class TestPastoralContext:
    """Test PastoralContext dataclass."""

    def test_default_values(self):
        ctx = PastoralContext()
        assert ctx.mode == PastoralMode.CURIOSITY
        assert ctx.tone == ToneConstraint.EXPLORATORY
        assert ctx.authority_level == AuthorityLevel.SUGGESTIVE
        assert ctx.vulnerability_detected is False
        assert ctx.crisis_indicators == []
        assert ctx.emotional_state == "neutral"
        assert ctx.requires_human_referral is False

    def test_custom_values(self):
        ctx = PastoralContext(
            mode=PastoralMode.CRISIS,
            tone=ToneConstraint.GENTLE,
            authority_level=AuthorityLevel.EXPLORATORY,
            vulnerability_detected=True,
            crisis_indicators=["self-harm risk"],
            emotional_state="distressed",
            requires_human_referral=True,
        )
        assert ctx.mode == PastoralMode.CRISIS
        assert ctx.tone == ToneConstraint.GENTLE
        assert ctx.vulnerability_detected is True
        assert ctx.crisis_indicators == ["self-harm risk"]
        assert ctx.requires_human_referral is True


class TestHalachicLandscape:
    """Test HalachicLandscape dataclass."""

    def test_default_values(self):
        landscape = HalachicLandscape()
        assert landscape.majority_view == ""
        assert landscape.minority_views == []
        assert landscape.underlying_principles == []
        assert landscape.precedents_for_leniency == []
        assert landscape.non_negotiable_boundaries == []
        assert landscape.sources_cited == []

    def test_custom_values(self):
        landscape = HalachicLandscape(
            majority_view="The mainstream view is...",
            minority_views=["Rav X holds differently"],
            underlying_principles=["kavod habriyot"],
            precedents_for_leniency=["B'sha'at hadchak"],
            non_negotiable_boundaries=["Shabbat"],
            sources_cited=["Shulchan Aruch", "Mishnah Berurah"],
        )
        assert landscape.majority_view == "The mainstream view is..."
        assert len(landscape.minority_views) == 1
        assert "kavod habriyot" in landscape.underlying_principles
        assert len(landscape.sources_cited) == 2


class TestMoralAssessment:
    """Test MoralAssessment dataclass."""

    def test_default_values(self):
        assessment = MoralAssessment()
        assert assessment.increases_holiness is True
        assert assessment.potential_harm == []
        assert assessment.dignity_preserved is True
        assert assessment.requires_reconsideration is False
        assert assessment.ethical_concerns == []

    def test_custom_values(self):
        assessment = MoralAssessment(
            increases_holiness=False,
            potential_harm=["May cause shame"],
            dignity_preserved=False,
            requires_reconsideration=True,
            ethical_concerns=["Response too harsh"],
        )
        assert assessment.increases_holiness is False
        assert assessment.requires_reconsideration is True
        assert len(assessment.potential_harm) == 1


class TestAgentContext:
    """Test AgentContext dataclass."""

    def test_minimal_context(self):
        ctx = AgentContext(user_message="What is Shabbat?")
        assert ctx.user_message == "What is Shabbat?"
        assert ctx.conversation_history == []
        assert ctx.pastoral_context is None
        assert ctx.halachic_landscape is None
        assert ctx.moral_assessment is None
        assert ctx.intermediate_response == ""
        assert ctx.final_response == ""
        assert ctx.metadata == {}

    def test_full_context(self):
        pastoral = PastoralContext(mode=PastoralMode.TEACHING)
        halachic = HalachicLandscape(majority_view="Test")
        moral = MoralAssessment()

        ctx = AgentContext(
            user_message="Question",
            conversation_history=[{"role": "user", "content": "Hi"}],
            pastoral_context=pastoral,
            halachic_landscape=halachic,
            moral_assessment=moral,
            intermediate_response="Draft response",
            final_response="Final response",
            metadata={"key": "value"},
        )

        assert ctx.pastoral_context.mode == PastoralMode.TEACHING
        assert ctx.halachic_landscape.majority_view == "Test"
        assert ctx.moral_assessment is not None
        assert ctx.metadata["key"] == "value"


class ConcreteAgent(BaseAgent):
    """Concrete implementation of BaseAgent for testing."""

    @property
    def system_prompt(self) -> str:
        return "Test system prompt"

    async def process(self, context: AgentContext) -> AgentContext:
        return context


class TestBaseAgent:
    """Test BaseAgent abstract class."""

    def test_initialization(self, mock_anthropic_client):
        agent = ConcreteAgent(mock_anthropic_client, "claude-sonnet-4-20250514")
        assert agent.client == mock_anthropic_client
        assert agent.model == "claude-sonnet-4-20250514"
        assert agent.name == "ConcreteAgent"

    def test_default_model(self, mock_anthropic_client):
        agent = ConcreteAgent(mock_anthropic_client)
        assert agent.model == "claude-sonnet-4-20250514"

    def test_system_prompt_property(self, mock_anthropic_client):
        agent = ConcreteAgent(mock_anthropic_client)
        assert agent.system_prompt == "Test system prompt"

    def test_call_claude(self, mock_anthropic_client, mock_claude_response):
        agent = ConcreteAgent(mock_anthropic_client)
        mock_anthropic_client.messages.create.return_value = mock_claude_response("Test response")

        result = agent._call_claude(
            [{"role": "user", "content": "Hello"}],
            "System prompt"
        )

        assert result == "Test response"
        mock_anthropic_client.messages.create.assert_called_once_with(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system="System prompt",
            messages=[{"role": "user", "content": "Hello"}],
        )

    def test_build_messages_simple(self, mock_anthropic_client):
        agent = ConcreteAgent(mock_anthropic_client)
        context = AgentContext(user_message="Test question")

        messages = agent._build_messages(context)

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Test question"

    def test_build_messages_with_history(self, mock_anthropic_client, sample_conversation_history):
        agent = ConcreteAgent(mock_anthropic_client)
        context = AgentContext(
            user_message="New question",
            conversation_history=sample_conversation_history,
        )

        messages = agent._build_messages(context)

        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["content"] == "New question"

    def test_build_messages_with_additional_context(self, mock_anthropic_client):
        agent = ConcreteAgent(mock_anthropic_client)
        context = AgentContext(user_message="Question")

        messages = agent._build_messages(context, "Extra context")

        assert "Extra context" in messages[0]["content"]
        assert "Question" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_process_abstract_method(self, mock_anthropic_client):
        agent = ConcreteAgent(mock_anthropic_client)
        context = AgentContext(user_message="Test")

        result = await agent.process(context)

        assert result == context

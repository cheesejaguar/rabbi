"""Tests for voice.py - MetaRabbinicVoiceAgent."""

import pytest
from unittest.mock import Mock

from app.agents.voice import MetaRabbinicVoiceAgent
from app.agents.base import (
    AgentContext,
    PastoralContext,
    PastoralMode,
    ToneConstraint,
    AuthorityLevel,
    HalachicLandscape,
    MoralAssessment,
)


class TestMetaRabbinicVoiceAgent:
    """Test MetaRabbinicVoiceAgent class."""

    @pytest.fixture
    def agent(self, mock_anthropic_client):
        return MetaRabbinicVoiceAgent(mock_anthropic_client)

    def test_initialization(self, agent):
        assert agent.name == "MetaRabbinicVoiceAgent"

    def test_system_prompt_contains_key_elements(self, agent):
        prompt = agent.system_prompt
        assert "Meta-Rabbinic Voice Agent" in prompt
        assert "humility" in prompt.lower()
        assert "I don't know" in prompt
        assert "This is hard" in prompt
        assert "not binding psak" in prompt.lower()
        assert "human rabbi" in prompt.lower()

    @pytest.mark.asyncio
    async def test_process_simple_message(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            "Shalom! This is a warm, pastoral response about your question."
        )

        context = AgentContext(user_message="What is Shabbat?")
        result = await agent.process(context)

        assert result.final_response is not None
        assert len(result.final_response) > 0

    @pytest.mark.asyncio
    async def test_process_with_pastoral_context(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            "I hear the difficulty in your question. Let me share some thoughts..."
        )

        pastoral = PastoralContext(
            mode=PastoralMode.COUNSELING,
            tone=ToneConstraint.GENTLE,
            authority_level=AuthorityLevel.SUGGESTIVE,
            vulnerability_detected=True,
            emotional_state="struggling",
            crisis_indicators=[],
            requires_human_referral=False,
        )
        context = AgentContext(
            user_message="I'm struggling with...",
            pastoral_context=pastoral,
        )
        result = await agent.process(context)

        assert result.final_response is not None

    @pytest.mark.asyncio
    async def test_process_with_halachic_landscape(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            "The tradition offers various perspectives on this..."
        )

        halachic = HalachicLandscape(
            majority_view="The main view is...",
            minority_views=["Alternative view"],
            underlying_principles=["kavod habriyot"],
            precedents_for_leniency=["In difficult cases"],
            non_negotiable_boundaries=["Core boundary"],
            sources_cited=["Shulchan Aruch"],
        )
        context = AgentContext(
            user_message="Question about halacha",
            halachic_landscape=halachic,
        )
        result = await agent.process(context)

        assert result.final_response is not None

    @pytest.mark.asyncio
    async def test_process_with_moral_assessment(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            "This is a sensitive topic, and I want to approach it with care..."
        )

        moral = MoralAssessment(
            increases_holiness=True,
            potential_harm=["Possible sensitivity"],
            dignity_preserved=True,
            requires_reconsideration=False,
            ethical_concerns=["Be gentle"],
        )
        context = AgentContext(
            user_message="Sensitive question",
            moral_assessment=moral,
        )
        result = await agent.process(context)

        assert result.final_response is not None

    @pytest.mark.asyncio
    async def test_process_with_crisis_referral(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            "I'm concerned about what you've shared. Please reach out to a counselor..."
        )

        pastoral = PastoralContext(
            mode=PastoralMode.CRISIS,
            tone=ToneConstraint.GENTLE,
            vulnerability_detected=True,
            crisis_indicators=["distress"],
            requires_human_referral=True,
        )
        context = AgentContext(
            user_message="I'm in crisis",
            pastoral_context=pastoral,
        )
        result = await agent.process(context)

        assert result.final_response is not None

    @pytest.mark.asyncio
    async def test_process_full_pipeline_context(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            "A comprehensive, warm response synthesizing all the context..."
        )

        pastoral = PastoralContext(
            mode=PastoralMode.TEACHING,
            tone=ToneConstraint.EXPLORATORY,
            authority_level=AuthorityLevel.SUGGESTIVE,
        )
        halachic = HalachicLandscape(
            majority_view="Main view",
            sources_cited=["Source1"],
        )
        moral = MoralAssessment(
            increases_holiness=True,
            dignity_preserved=True,
        )

        context = AgentContext(
            user_message="Complex question",
            pastoral_context=pastoral,
            halachic_landscape=halachic,
            moral_assessment=moral,
        )
        result = await agent.process(context)

        assert result.final_response is not None
        assert len(result.final_response) > 0

    @pytest.mark.asyncio
    async def test_final_response_is_set(self, agent, mock_claude_response):
        expected_response = "This is the final rabbinic response."
        agent.client.messages.create.return_value = mock_claude_response(expected_response)

        context = AgentContext(user_message="Question")
        result = await agent.process(context)

        assert result.final_response == expected_response

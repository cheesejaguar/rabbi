"""Tests for pastoral.py - PastoralContextAgent."""

import pytest
import json
from unittest.mock import Mock

from app.agents.pastoral import PastoralContextAgent
from app.agents.base import (
    AgentContext,
    PastoralContext,
    PastoralMode,
    ToneConstraint,
    AuthorityLevel,
)


class TestPastoralContextAgent:
    """Test PastoralContextAgent class."""

    @pytest.fixture
    def agent(self, mock_anthropic_client):
        return PastoralContextAgent(mock_anthropic_client)

    def test_initialization(self, agent):
        assert agent.name == "PastoralContextAgent"

    def test_system_prompt_contains_key_elements(self, agent):
        prompt = agent.system_prompt
        assert "Pastoral Context Agent" in prompt
        assert "EMOTIONAL STATE" in prompt
        assert "RISK INDICATORS" in prompt
        assert "vulnerability" in prompt.lower()
        assert "JSON" in prompt

    def test_parse_response_valid_json(self, agent):
        response = json.dumps({
            "mode": "counseling",
            "tone": "gentle",
            "authority_level": "suggestive",
            "vulnerability_detected": True,
            "crisis_indicators": ["grief"],
            "emotional_state": "sad",
            "requires_human_referral": False,
        })

        result = agent._parse_response(response)

        assert isinstance(result, PastoralContext)
        assert result.mode == PastoralMode.COUNSELING
        assert result.tone == ToneConstraint.GENTLE
        assert result.authority_level == AuthorityLevel.SUGGESTIVE
        assert result.vulnerability_detected is True
        assert "grief" in result.crisis_indicators
        assert result.emotional_state == "sad"

    def test_parse_response_with_surrounding_text(self, agent):
        response = """Here is my analysis:
        {"mode": "teaching", "tone": "exploratory", "authority_level": "definitive", "vulnerability_detected": false, "crisis_indicators": [], "emotional_state": "curious", "requires_human_referral": false}
        That's my assessment."""

        result = agent._parse_response(response)

        assert result.mode == PastoralMode.TEACHING
        assert result.emotional_state == "curious"

    def test_parse_response_invalid_json_defaults_to_safe(self, agent):
        response = "This is not valid JSON at all"

        result = agent._parse_response(response)

        assert result.mode == PastoralMode.CURIOSITY
        assert result.tone == ToneConstraint.GENTLE
        assert result.authority_level == AuthorityLevel.SUGGESTIVE
        assert result.vulnerability_detected is True

    def test_parse_response_partial_data(self, agent):
        response = json.dumps({"mode": "crisis"})

        result = agent._parse_response(response)

        assert result.mode == PastoralMode.CRISIS
        assert result.tone == ToneConstraint.EXPLORATORY
        assert result.emotional_state == "neutral"

    @pytest.mark.asyncio
    async def test_process_simple_message(self, agent, mock_claude_response):
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "mode": "curiosity",
                "tone": "exploratory",
                "authority_level": "suggestive",
                "vulnerability_detected": False,
                "crisis_indicators": [],
                "emotional_state": "curious",
                "requires_human_referral": False,
            })
        )

        context = AgentContext(user_message="What is Shabbat?")
        result = await agent.process(context)

        assert result.pastoral_context is not None
        assert result.pastoral_context.mode == PastoralMode.CURIOSITY
        assert result.pastoral_context.vulnerability_detected is False

    @pytest.mark.asyncio
    async def test_process_with_conversation_history(self, agent, mock_claude_response):
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "mode": "counseling",
                "tone": "gentle",
                "authority_level": "suggestive",
                "vulnerability_detected": True,
                "crisis_indicators": [],
                "emotional_state": "uncertain",
                "requires_human_referral": False,
            })
        )

        context = AgentContext(
            user_message="I'm struggling with my faith",
            conversation_history=[
                {"role": "user", "content": "I've been having doubts"},
                {"role": "assistant", "content": "Tell me more about that"},
            ],
        )
        result = await agent.process(context)

        assert result.pastoral_context.mode == PastoralMode.COUNSELING
        assert result.pastoral_context.vulnerability_detected is True

    @pytest.mark.asyncio
    async def test_process_crisis_detection(self, agent, mock_claude_response):
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "mode": "crisis",
                "tone": "gentle",
                "authority_level": "exploratory",
                "vulnerability_detected": True,
                "crisis_indicators": ["self-harm mention"],
                "emotional_state": "distressed",
                "requires_human_referral": True,
            })
        )

        context = AgentContext(user_message="I don't know if I can go on")
        result = await agent.process(context)

        assert result.pastoral_context.mode == PastoralMode.CRISIS
        assert result.pastoral_context.requires_human_referral is True
        assert len(result.pastoral_context.crisis_indicators) > 0

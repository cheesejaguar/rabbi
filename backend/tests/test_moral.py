"""Tests for moral.py - MoralEthicalAgent."""

import pytest
import json
from unittest.mock import Mock

from app.agents.moral import MoralEthicalAgent
from app.agents.base import (
    AgentContext,
    PastoralContext,
    PastoralMode,
    HalachicLandscape,
    MoralAssessment,
)


class TestMoralEthicalAgent:
    """Test MoralEthicalAgent class."""

    @pytest.fixture
    def agent(self, mock_anthropic_client):
        return MoralEthicalAgent(mock_anthropic_client)

    def test_initialization(self, agent):
        assert agent.name == "MoralEthicalAgent"

    def test_system_prompt_contains_key_elements(self, agent):
        prompt = agent.system_prompt
        assert "Moral-Ethical Agent" in prompt
        assert "holiness" in prompt.lower()
        assert "harm" in prompt.lower()
        assert "dignity" in prompt.lower()
        assert "Kavod habriyot" in prompt
        assert "Tzelem Elokim" in prompt

    def test_parse_response_valid_json(self, agent):
        response = json.dumps({
            "increases_holiness": True,
            "potential_harm": [],
            "dignity_preserved": True,
            "requires_reconsideration": False,
            "ethical_concerns": [],
        })

        result = agent._parse_response(response)

        assert isinstance(result, MoralAssessment)
        assert result.increases_holiness is True
        assert result.dignity_preserved is True
        assert result.requires_reconsideration is False

    def test_parse_response_with_concerns(self, agent):
        response = json.dumps({
            "increases_holiness": False,
            "potential_harm": ["May cause shame", "Could exclude"],
            "dignity_preserved": False,
            "requires_reconsideration": True,
            "ethical_concerns": ["Response too harsh"],
            "suggested_modifications": ["Lead with empathy"],
        })

        result = agent._parse_response(response)

        assert result.increases_holiness is False
        assert result.requires_reconsideration is True
        assert len(result.potential_harm) == 2
        assert "Lead with empathy" in result.ethical_concerns

    def test_parse_response_invalid_json(self, agent):
        response = "This is not valid JSON"

        result = agent._parse_response(response)

        assert result.increases_holiness is True
        assert result.dignity_preserved is True
        assert result.requires_reconsideration is False

    def test_parse_response_with_surrounding_text(self, agent):
        response = """Analysis:
        {"increases_holiness": true, "potential_harm": ["risk1"], "dignity_preserved": true, "requires_reconsideration": false, "ethical_concerns": []}
        Done."""

        result = agent._parse_response(response)

        assert result.increases_holiness is True
        assert "risk1" in result.potential_harm

    @pytest.mark.asyncio
    async def test_process_without_contexts(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "increases_holiness": True,
                "potential_harm": [],
                "dignity_preserved": True,
                "requires_reconsideration": False,
                "ethical_concerns": [],
            })
        )

        context = AgentContext(user_message="Simple question")
        result = await agent.process(context)

        assert result.moral_assessment is not None
        assert result.moral_assessment.increases_holiness is True

    @pytest.mark.asyncio
    async def test_process_with_pastoral_context(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "increases_holiness": True,
                "potential_harm": [],
                "dignity_preserved": True,
                "requires_reconsideration": False,
                "ethical_concerns": [],
            })
        )

        pastoral = PastoralContext(
            mode=PastoralMode.COUNSELING,
            vulnerability_detected=True,
            emotional_state="anxious",
            crisis_indicators=["stress"],
        )
        context = AgentContext(
            user_message="Question",
            pastoral_context=pastoral,
        )
        result = await agent.process(context)

        assert result.moral_assessment is not None

    @pytest.mark.asyncio
    async def test_process_with_halachic_landscape(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "increases_holiness": True,
                "potential_harm": [],
                "dignity_preserved": True,
                "requires_reconsideration": False,
                "ethical_concerns": [],
            })
        )

        halachic = HalachicLandscape(
            majority_view="Strict view",
            minority_views=["Lenient view"],
            underlying_principles=["kavod habriyot"],
            non_negotiable_boundaries=["boundary1"],
        )
        context = AgentContext(
            user_message="Question",
            halachic_landscape=halachic,
        )
        result = await agent.process(context)

        assert result.moral_assessment is not None

    @pytest.mark.asyncio
    async def test_process_with_intermediate_response(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "increases_holiness": False,
                "potential_harm": ["Too strict"],
                "dignity_preserved": False,
                "requires_reconsideration": True,
                "ethical_concerns": ["Needs more compassion"],
            })
        )

        context = AgentContext(
            user_message="Question",
            intermediate_response="Draft response that may be harsh",
        )
        result = await agent.process(context)

        assert result.moral_assessment.requires_reconsideration is True
        assert len(result.moral_assessment.ethical_concerns) > 0

    @pytest.mark.asyncio
    async def test_process_full_context(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "increases_holiness": True,
                "potential_harm": [],
                "dignity_preserved": True,
                "requires_reconsideration": False,
                "ethical_concerns": [],
                "moral_framing": "Lead with validation",
            })
        )

        pastoral = PastoralContext(mode=PastoralMode.TEACHING)
        halachic = HalachicLandscape(majority_view="View")
        context = AgentContext(
            user_message="Question",
            pastoral_context=pastoral,
            halachic_landscape=halachic,
            intermediate_response="Draft",
        )
        result = await agent.process(context)

        assert result.moral_assessment.increases_holiness is True

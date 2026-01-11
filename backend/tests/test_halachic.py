"""Tests for halachic.py - HalachicReasoningAgent."""

import pytest
import json
from unittest.mock import Mock

from app.agents.halachic import HalachicReasoningAgent
from app.agents.base import (
    AgentContext,
    PastoralContext,
    PastoralMode,
    ToneConstraint,
    AuthorityLevel,
    HalachicLandscape,
)


class TestHalachicReasoningAgent:
    """Test HalachicReasoningAgent class."""

    @pytest.fixture
    def agent(self, mock_anthropic_client):
        return HalachicReasoningAgent(mock_anthropic_client)

    def test_initialization(self, agent):
        assert agent.name == "HalachicReasoningAgent"

    def test_system_prompt_contains_key_elements(self, agent):
        prompt = agent.system_prompt
        assert "Halachic Reasoning Agent" in prompt
        assert "pluralistic" in prompt.lower()
        assert "Talmud" in prompt
        assert "minority" in prompt.lower()
        assert "leniency" in prompt.lower()

    def test_parse_response_valid_json(self, agent):
        response = json.dumps({
            "majority_view": "The mainstream position is...",
            "minority_views": ["Rav X disagrees", "Some hold differently"],
            "underlying_principles": ["kavod habriyot", "pikuach nefesh"],
            "precedents_for_leniency": ["In pressing circumstances"],
            "non_negotiable_boundaries": ["Shabbat observance"],
            "sources_cited": ["Shulchan Aruch", "Mishnah Berurah"],
        })

        result = agent._parse_response(response)

        assert isinstance(result, HalachicLandscape)
        assert "mainstream" in result.majority_view
        assert len(result.minority_views) == 2
        assert "kavod habriyot" in result.underlying_principles
        assert len(result.sources_cited) == 2

    def test_parse_response_with_summary_for_user(self, agent):
        response = json.dumps({
            "majority_view": "Technical view",
            "summary_for_user": "This is the accessible summary",
            "minority_views": [],
            "underlying_principles": [],
            "precedents_for_leniency": [],
            "non_negotiable_boundaries": [],
            "sources_cited": [],
        })

        result = agent._parse_response(response)

        assert result.majority_view == "This is the accessible summary"

    def test_parse_response_invalid_json(self, agent):
        response = "Not valid JSON"

        result = agent._parse_response(response)

        assert "thoughtful answer" in result.majority_view
        assert "Human dignity" in result.underlying_principles

    def test_parse_response_with_surrounding_text(self, agent):
        response = """Here is the analysis:
        {"majority_view": "Test view", "minority_views": [], "underlying_principles": ["test"], "precedents_for_leniency": [], "non_negotiable_boundaries": [], "sources_cited": ["Talmud"]}
        End of response."""

        result = agent._parse_response(response)

        assert result.majority_view == "Test view"
        assert "Talmud" in result.sources_cited

    @pytest.mark.asyncio
    async def test_process_without_pastoral_context(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "The answer is...",
                "minority_views": [],
                "underlying_principles": ["principle1"],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="What is the law about X?")
        result = await agent.process(context)

        assert result.halachic_landscape is not None
        assert result.halachic_landscape.majority_view == "The answer is..."
        assert result.intermediate_response == "The answer is..."

    @pytest.mark.asyncio
    async def test_process_with_pastoral_context(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "With compassion, the view is...",
                "minority_views": ["Lenient view"],
                "underlying_principles": ["kavod habriyot"],
                "precedents_for_leniency": ["In difficult times"],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        pastoral = PastoralContext(
            mode=PastoralMode.COUNSELING,
            vulnerability_detected=True,
            emotional_state="distressed",
        )
        context = AgentContext(
            user_message="I'm struggling with...",
            pastoral_context=pastoral,
        )
        result = await agent.process(context)

        assert result.halachic_landscape is not None
        assert len(result.halachic_landscape.precedents_for_leniency) > 0

    @pytest.mark.asyncio
    async def test_process_sets_intermediate_response(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "Main view here",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="Question")
        result = await agent.process(context)

        assert result.intermediate_response == "Main view here"

    @pytest.mark.asyncio
    async def test_process_empty_majority_view_no_intermediate(self, agent, mock_claude_response):
        agent.client.messages.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="Question")
        result = await agent.process(context)

        assert result.intermediate_response == ""

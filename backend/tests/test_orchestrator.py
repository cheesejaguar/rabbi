"""Tests for orchestrator.py - RabbiOrchestrator."""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch

from app.agents.orchestrator import RabbiOrchestrator
from app.agents.base import (
    AgentContext,
    PastoralContext,
    PastoralMode,
    ToneConstraint,
    AuthorityLevel,
    HalachicLandscape,
    MoralAssessment,
)


def create_llm_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Helper to create mock LLM response with usage metrics."""
    response = Mock()
    choice = Mock()
    message = Mock()
    message.content = text
    choice.message = message
    response.choices = [choice]
    # Add usage metrics for cost calculation
    usage = Mock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens
    response.usage = usage
    return response


class TestRabbiOrchestrator:
    """Test RabbiOrchestrator class."""

    def test_initialization_with_api_key(self):
        with patch('app.agents.orchestrator.LLMClient') as mock_openai:
            orchestrator = RabbiOrchestrator(api_key="test-key")
            mock_openai.assert_called_once_with(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
            )
            assert orchestrator.model == "anthropic/claude-sonnet-4-20250514"

    def test_initialization_with_custom_base_url(self):
        with patch('app.agents.orchestrator.LLMClient') as mock_openai:
            orchestrator = RabbiOrchestrator(
                api_key="test-key",
                base_url="https://custom.api/v1",
            )
            mock_openai.assert_called_once_with(
                api_key="test-key",
                base_url="https://custom.api/v1",
            )

    def test_initialization_custom_model(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(
                api_key="key",
                model="anthropic/claude-opus-4-20250514",
            )
            assert orchestrator.model == "anthropic/claude-opus-4-20250514"

    def test_agents_initialized(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(api_key="test-key")
            assert orchestrator.pastoral_agent is not None
            assert orchestrator.halachic_agent is not None
            assert orchestrator.moral_agent is not None
            assert orchestrator.voice_agent is not None

    @pytest.mark.asyncio
    async def test_process_message_full_pipeline(self):
        with patch('app.agents.orchestrator.LLMClient') as mock_openai:
            responses = [
                json.dumps({
                    "mode": "curiosity",
                    "tone": "exploratory",
                    "authority_level": "suggestive",
                    "vulnerability_detected": False,
                    "crisis_indicators": [],
                    "emotional_state": "curious",
                    "requires_human_referral": False,
                }),
                json.dumps({
                    "majority_view": "The mainstream view",
                    "minority_views": [],
                    "underlying_principles": ["principle1"],
                    "precedents_for_leniency": [],
                    "non_negotiable_boundaries": [],
                    "sources_cited": ["Source1"],
                }),
                json.dumps({
                    "increases_holiness": True,
                    "potential_harm": [],
                    "dignity_preserved": True,
                    "requires_reconsideration": False,
                    "ethical_concerns": [],
                }),
                "This is the final warm response from the rebbe.dev.",
            ]

            call_count = [0]
            def side_effect(*args, **kwargs):
                resp = create_llm_response(responses[min(call_count[0], len(responses) - 1)])
                call_count[0] += 1
                return resp

            mock_client = Mock()
            mock_client.chat.completions.create.side_effect = side_effect
            mock_openai.return_value = mock_client

            orchestrator = RabbiOrchestrator(api_key="test-key")
            result = await orchestrator.process_message("What is Shabbat?")

            assert "response" in result
            assert result["response"] == "This is the final warm response from the rebbe.dev."
            assert "requires_human_referral" in result
            assert "metadata" in result

    @pytest.mark.asyncio
    async def test_process_message_with_conversation_history(self):
        with patch('app.agents.orchestrator.LLMClient') as mock_openai:
            responses = [
                json.dumps({"mode": "teaching", "tone": "exploratory", "authority_level": "suggestive", "vulnerability_detected": False, "crisis_indicators": [], "emotional_state": "engaged", "requires_human_referral": False}),
                json.dumps({"majority_view": "View", "minority_views": [], "underlying_principles": [], "precedents_for_leniency": [], "non_negotiable_boundaries": [], "sources_cited": []}),
                json.dumps({"increases_holiness": True, "potential_harm": [], "dignity_preserved": True, "requires_reconsideration": False, "ethical_concerns": []}),
                "Final response",
            ]

            call_count = [0]
            def side_effect(*args, **kwargs):
                resp = create_llm_response(responses[min(call_count[0], len(responses) - 1)])
                call_count[0] += 1
                return resp

            mock_client = Mock()
            mock_client.chat.completions.create.side_effect = side_effect
            mock_openai.return_value = mock_client

            orchestrator = RabbiOrchestrator(api_key="test-key")
            history = [
                {"role": "user", "content": "Previous question"},
                {"role": "assistant", "content": "Previous answer"},
            ]
            result = await orchestrator.process_message(
                "Follow-up question",
                conversation_history=history,
            )

            assert result["response"] == "Final response"

    @pytest.mark.asyncio
    async def test_process_message_with_reconsideration(self):
        with patch('app.agents.orchestrator.LLMClient') as mock_openai:
            responses = [
                json.dumps({"mode": "counseling", "tone": "gentle", "authority_level": "suggestive", "vulnerability_detected": True, "crisis_indicators": [], "emotional_state": "vulnerable", "requires_human_referral": False}),
                json.dumps({"majority_view": "Strict view", "minority_views": [], "underlying_principles": [], "precedents_for_leniency": [], "non_negotiable_boundaries": [], "sources_cited": []}),
                json.dumps({"increases_holiness": False, "potential_harm": ["Too harsh"], "dignity_preserved": False, "requires_reconsideration": True, "ethical_concerns": ["Needs compassion"]}),
                json.dumps({"majority_view": "Compassionate view", "minority_views": [], "underlying_principles": ["kavod habriyot"], "precedents_for_leniency": ["Lenient option"], "non_negotiable_boundaries": [], "sources_cited": []}),
                "A gentle, reconsidered response",
            ]

            call_count = [0]
            def side_effect(*args, **kwargs):
                resp = create_llm_response(responses[min(call_count[0], len(responses) - 1)])
                call_count[0] += 1
                return resp

            mock_client = Mock()
            mock_client.chat.completions.create.side_effect = side_effect
            mock_openai.return_value = mock_client

            orchestrator = RabbiOrchestrator(api_key="test-key")
            result = await orchestrator.process_message("Sensitive question")

            assert result["metadata"]["moral_reconsideration"] is True
            assert result["response"] == "A gentle, reconsidered response"

    @pytest.mark.asyncio
    async def test_process_message_crisis_detection(self):
        with patch('app.agents.orchestrator.LLMClient') as mock_openai:
            responses = [
                json.dumps({"mode": "crisis", "tone": "gentle", "authority_level": "exploratory", "vulnerability_detected": True, "crisis_indicators": ["self-harm"], "emotional_state": "distressed", "requires_human_referral": True}),
                json.dumps({"majority_view": "Supportive view", "minority_views": [], "underlying_principles": ["pikuach nefesh"], "precedents_for_leniency": [], "non_negotiable_boundaries": [], "sources_cited": []}),
                json.dumps({"increases_holiness": True, "potential_harm": [], "dignity_preserved": True, "requires_reconsideration": False, "ethical_concerns": []}),
                "Please reach out for support. You matter.",
            ]

            call_count = [0]
            def side_effect(*args, **kwargs):
                resp = create_llm_response(responses[min(call_count[0], len(responses) - 1)])
                call_count[0] += 1
                return resp

            mock_client = Mock()
            mock_client.chat.completions.create.side_effect = side_effect
            mock_openai.return_value = mock_client

            orchestrator = RabbiOrchestrator(api_key="test-key")
            result = await orchestrator.process_message("I'm in crisis")

            assert result["requires_human_referral"] is True
            assert result["metadata"]["pastoral_mode"] == "crisis"
            assert result["metadata"]["vulnerability_detected"] is True
            assert "crisis_indicators" in result["metadata"]

    def test_build_response_minimal_context(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(api_key="test-key")

            context = AgentContext(
                user_message="Test",
                final_response="Response text",
            )

            result = orchestrator._build_response(context)

            assert result["response"] == "Response text"
            assert result["requires_human_referral"] is False
            assert result["metadata"]["pastoral_mode"] is None
            assert result["metadata"]["moral_reconsideration"] is False

    def test_build_response_with_pastoral_context(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(api_key="test-key")

            pastoral = PastoralContext(
                mode=PastoralMode.COUNSELING,
                vulnerability_detected=True,
                emotional_state="anxious",
                requires_human_referral=True,
                crisis_indicators=["stress"],
            )
            context = AgentContext(
                user_message="Test",
                final_response="Response",
                pastoral_context=pastoral,
            )

            result = orchestrator._build_response(context)

            assert result["requires_human_referral"] is True
            assert result["metadata"]["pastoral_mode"] == "counseling"
            assert result["metadata"]["vulnerability_detected"] is True
            assert result["metadata"]["emotional_state"] == "anxious"
            assert result["metadata"]["crisis_indicators"] == ["stress"]

    def test_build_response_with_halachic_landscape(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(api_key="test-key")

            halachic = HalachicLandscape(
                sources_cited=["Talmud", "Shulchan Aruch"],
                underlying_principles=["kavod habriyot"],
            )
            context = AgentContext(
                user_message="Test",
                final_response="Response",
                halachic_landscape=halachic,
            )

            result = orchestrator._build_response(context)

            assert result["metadata"]["sources_cited"] == ["Talmud", "Shulchan Aruch"]
            assert result["metadata"]["principles"] == ["kavod habriyot"]

    def test_build_response_with_reconsideration_metadata(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(api_key="test-key")

            context = AgentContext(
                user_message="Test",
                final_response="Response",
                metadata={"moral_reconsideration": True},
            )

            result = orchestrator._build_response(context)

            assert result["metadata"]["moral_reconsideration"] is True

    @pytest.mark.asyncio
    async def test_get_greeting(self):
        with patch('app.agents.orchestrator.LLMClient'):
            orchestrator = RabbiOrchestrator(api_key="test-key")
            greeting = await orchestrator.get_greeting()

            assert "Shalom" in greeting
            assert "AI" in greeting
            assert "rabbi" in greeting.lower()

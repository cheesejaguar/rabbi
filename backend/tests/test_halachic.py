"""Tests for halachic.py - HalachicReasoningAgent and RAG gating."""

import pytest
import json
from unittest.mock import Mock, MagicMock

from app.agents.halachic import HalachicReasoningAgent, _should_use_rag
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
        agent.client.chat.completions.create.return_value = mock_claude_response(
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
        agent.client.chat.completions.create.return_value = mock_claude_response(
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
        agent.client.chat.completions.create.return_value = mock_claude_response(
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
        agent.client.chat.completions.create.return_value = mock_claude_response(
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

    @pytest.mark.asyncio
    async def test_process_sets_rag_used_metadata(self, agent, mock_claude_response):
        """rag_used flag should appear in context metadata after process()."""
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "View",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        # Halachic keyword → RAG should be used (but no retriever attached)
        context = AgentContext(user_message="What does the Talmud say about this?")
        result = await agent.process(context)
        assert "rag_used" in result.metadata
        assert result.metadata["rag_used"] is True

    @pytest.mark.asyncio
    async def test_process_rag_skipped_for_greeting(self, agent, mock_claude_response):
        """RAG should be skipped for simple greetings."""
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "View",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="Hello!")
        result = await agent.process(context)
        assert result.metadata["rag_used"] is False

    @pytest.mark.asyncio
    async def test_process_rag_calls_retriever_when_appropriate(self, mock_anthropic_client, mock_claude_response):
        """When RAG is warranted and a retriever is available, it should be called."""
        mock_retriever = MagicMock()
        mock_retriever.ensure_loaded = MagicMock()
        mock_retriever.search_formatted = MagicMock(return_value="Source text here")

        agent = HalachicReasoningAgent(mock_anthropic_client, retriever=mock_retriever)
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "View",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="What does the Shulchan Aruch say about Shabbat?")
        result = await agent.process(context)

        mock_retriever.ensure_loaded.assert_called_once()
        mock_retriever.search_formatted.assert_called_once()
        assert result.metadata["rag_used"] is True

    @pytest.mark.asyncio
    async def test_process_rag_not_called_when_skipped(self, mock_anthropic_client, mock_claude_response):
        """When RAG is not warranted, retriever should not be called even if available."""
        mock_retriever = MagicMock()
        mock_retriever.ensure_loaded = MagicMock()
        mock_retriever.search_formatted = MagicMock(return_value="Source text here")

        agent = HalachicReasoningAgent(mock_anthropic_client, retriever=mock_retriever)
        agent.client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({
                "majority_view": "View",
                "minority_views": [],
                "underlying_principles": [],
                "precedents_for_leniency": [],
                "non_negotiable_boundaries": [],
                "sources_cited": [],
            })
        )

        context = AgentContext(user_message="Thank you!")
        result = await agent.process(context)

        mock_retriever.ensure_loaded.assert_not_called()
        mock_retriever.search_formatted.assert_not_called()
        assert result.metadata["rag_used"] is False


class TestShouldUseRag:
    """Test the _should_use_rag gating function."""

    # --- Messages that SHOULD trigger RAG ---

    def test_halachic_keyword_triggers_rag(self):
        assert _should_use_rag("What does the Talmud say about honoring parents?") is True

    def test_shabbat_triggers_rag(self):
        assert _should_use_rag("Can I use electricity on Shabbat?") is True

    def test_kashrut_triggers_rag(self):
        assert _should_use_rag("Is this food kosher?") is True

    def test_source_request_triggers_rag(self):
        assert _should_use_rag("What are the sources for this ruling?") is True

    def test_rambam_triggers_rag(self):
        assert _should_use_rag("What does the Rambam say about prayer?") is True

    def test_torah_triggers_rag(self):
        assert _should_use_rag("I'm studying Torah and have a question") is True

    def test_mitzvah_triggers_rag(self):
        assert _should_use_rag("How do I fulfill this mitzvah properly?") is True

    def test_bracha_triggers_rag(self):
        assert _should_use_rag("What bracha do I make on this food?") is True

    def test_tefillin_triggers_rag(self):
        assert _should_use_rag("When should I put on tefillin?") is True

    def test_conversion_triggers_rag(self):
        assert _should_use_rag("I am interested in conversion to Judaism") is True

    def test_marriage_triggers_rag(self):
        assert _should_use_rag("What are the laws of marriage in Judaism?") is True

    def test_mourning_triggers_rag(self):
        assert _should_use_rag("What are the rules for sitting shiva?") is True

    def test_permitted_forbidden_triggers_rag(self):
        assert _should_use_rag("Is it permitted to eat before davening?") is True

    def test_according_to_triggers_rag(self):
        assert _should_use_rag("According to halacha, what should I do?") is True

    def test_chazal_triggers_rag(self):
        assert _should_use_rag("What do Chazal teach about this topic?") is True

    def test_curiosity_mode_practice_question(self):
        """Practice questions in curiosity mode should trigger RAG."""
        assert _should_use_rag("Can I do this on a Jewish holiday?", PastoralMode.CURIOSITY) is True

    def test_teaching_mode_practice_question(self):
        """Practice questions in teaching mode should trigger RAG."""
        assert _should_use_rag("Should I pray in the morning or evening?", PastoralMode.TEACHING) is True

    def test_teaching_mode_rabbi_question(self):
        assert _should_use_rag("What would a rabbi say about this?", PastoralMode.TEACHING) is True

    def test_yom_kippur_triggers_rag(self):
        assert _should_use_rag("How do I prepare for Yom Kippur?", PastoralMode.CURIOSITY) is True

    def test_pesach_triggers_rag(self):
        assert _should_use_rag("What do I need for Pesach?", PastoralMode.TEACHING) is True

    # --- Messages that should NOT trigger RAG ---

    def test_greeting_skips_rag(self):
        assert _should_use_rag("Hello!") is False

    def test_shalom_greeting_skips_rag(self):
        assert _should_use_rag("Shalom") is False

    def test_thanks_skips_rag(self):
        assert _should_use_rag("Thank you!") is False

    def test_toda_skips_rag(self):
        assert _should_use_rag("Toda!") is False

    def test_goodbye_skips_rag(self):
        assert _should_use_rag("Goodbye!") is False

    def test_ok_skips_rag(self):
        assert _should_use_rag("Ok") is False

    def test_short_message_skips_rag(self):
        assert _should_use_rag("Hi") is False

    def test_empty_message_skips_rag(self):
        assert _should_use_rag("") is False

    def test_whitespace_only_skips_rag(self):
        assert _should_use_rag("   ") is False

    def test_who_are_you_skips_rag(self):
        assert _should_use_rag("Who are you?") is False

    def test_what_can_you_do_skips_rag(self):
        assert _should_use_rag("What can you do?") is False

    def test_crisis_mode_skips_rag(self):
        """Crisis mode should always skip RAG, even with halachic keywords."""
        assert _should_use_rag("I can't keep Shabbat anymore, I'm falling apart",
                               PastoralMode.CRISIS) is False

    def test_crisis_mode_skips_rag_torah(self):
        assert _should_use_rag("The Torah feels like a burden",
                               PastoralMode.CRISIS) is False

    def test_generic_life_question_no_rag(self):
        """Generic life advice without halachic content should skip RAG."""
        assert _should_use_rag("I'm feeling stressed about work") is False

    def test_relationship_advice_no_rag(self):
        assert _should_use_rag("My friend hurt my feelings") is False

    def test_good_morning_skips_rag(self):
        assert _should_use_rag("Good morning!") is False

    def test_i_see_skips_rag(self):
        assert _should_use_rag("I see") is False

    def test_understood_skips_rag(self):
        assert _should_use_rag("Understood.") is False

    # --- Edge cases ---

    def test_no_pastoral_mode_with_keyword(self):
        """Even without pastoral mode, halachic keywords should trigger RAG."""
        assert _should_use_rag("Tell me about kashrut") is True

    def test_no_pastoral_mode_without_keyword(self):
        """Without pastoral mode or keywords, generic messages skip RAG."""
        assert _should_use_rag("I need some general life advice") is False

    def test_counseling_mode_with_keyword(self):
        """Counseling mode with halachic keywords should still trigger RAG."""
        assert _should_use_rag("I'm struggling with Shabbat observance",
                               PastoralMode.COUNSELING) is True

    def test_counseling_mode_without_keyword(self):
        """Counseling mode without halachic keywords should skip RAG."""
        assert _should_use_rag("I'm going through a tough time",
                               PastoralMode.COUNSELING) is False

    def test_case_insensitive_keywords(self):
        """Keywords should match regardless of case."""
        assert _should_use_rag("What does the TALMUD say?") is True
        assert _should_use_rag("Is this KOSHER?") is True

    def test_keyword_as_substring(self):
        """Keywords embedded in longer words should still match."""
        assert _should_use_rag("I want to learn about halachic decisions") is True

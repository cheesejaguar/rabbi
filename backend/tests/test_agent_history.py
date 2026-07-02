"""Tests that all reasoning agents receive conversation history in their prompts.

Follow-up questions ("what about the lenient view you mentioned?") are
meaningless without prior turns, so the halachic, moral, and voice agents
must include recent history — not just the pastoral agent.
"""

import json
import pytest
from unittest.mock import MagicMock

from app.agents.base import AgentContext, BaseAgent
from app.agents.halachic import HalachicReasoningAgent
from app.agents.moral import MoralEthicalAgent
from app.agents.voice import MetaRabbinicVoiceAgent


HISTORY = [
    {"role": "user", "content": "Can I carry keys on Shabbat?"},
    {"role": "assistant", "content": "Within an eruv, most authorities permit carrying."},
    {"role": "user", "content": "What about the lenient view you mentioned?"},
]


def _sent_prompt(mock_client):
    """Extract the user-message content sent to the mocked LLM."""
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    return kwargs["messages"][-1]["content"]


class TestFormatHistory:
    """Test the shared _format_history helper."""

    def _agent(self, mock_anthropic_client):
        class Dummy(BaseAgent):
            @property
            def system_prompt(self):
                return "test"

            async def process(self, context):
                return context

        return Dummy(mock_anthropic_client)

    def test_empty_history_returns_empty_string(self, mock_anthropic_client):
        agent = self._agent(mock_anthropic_client)
        context = AgentContext(user_message="hello")
        assert agent._format_history(context) == ""

    def test_history_is_labeled_and_truncated(self, mock_anthropic_client):
        agent = self._agent(mock_anthropic_client)
        context = AgentContext(
            user_message="follow-up",
            conversation_history=[
                {"role": "user", "content": "x" * 900},
                {"role": "assistant", "content": "short answer"},
            ],
        )
        block = agent._format_history(context, max_chars=500)
        assert "CONVERSATION SO FAR" in block
        assert "User: " in block
        assert "Rebbe: short answer" in block
        # Long messages truncated with ellipsis
        assert ("x" * 500 + "...") in block
        assert ("x" * 501) not in block

    def test_only_trailing_messages_included(self, mock_anthropic_client):
        agent = self._agent(mock_anthropic_client)
        history = [{"role": "user", "content": f"message {i}"} for i in range(10)]
        context = AgentContext(user_message="q", conversation_history=history)
        block = agent._format_history(context, max_messages=6)
        assert "message 3" not in block
        assert "message 4" in block
        assert "message 9" in block


class TestAgentsReceiveHistory:
    """Each downstream agent's prompt must include the conversation."""

    @pytest.mark.asyncio
    async def test_halachic_prompt_includes_history(self, mock_anthropic_client, mock_claude_response):
        agent = HalachicReasoningAgent(mock_anthropic_client)
        mock_anthropic_client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({"majority_view": "View", "sources_cited": []})
        )
        context = AgentContext(
            user_message="What about the lenient view you mentioned?",
            conversation_history=HISTORY,
        )
        await agent.process(context)

        prompt = _sent_prompt(mock_anthropic_client)
        assert "CONVERSATION SO FAR" in prompt
        assert "Can I carry keys on Shabbat?" in prompt

    @pytest.mark.asyncio
    async def test_moral_prompt_includes_history(self, mock_anthropic_client, mock_claude_response):
        agent = MoralEthicalAgent(mock_anthropic_client)
        mock_anthropic_client.chat.completions.create.return_value = mock_claude_response(
            json.dumps({"increases_holiness": True, "dignity_preserved": True})
        )
        context = AgentContext(
            user_message="What about the lenient view you mentioned?",
            conversation_history=HISTORY,
            intermediate_response="Draft response",
        )
        await agent.process(context)

        prompt = _sent_prompt(mock_anthropic_client)
        assert "CONVERSATION SO FAR" in prompt
        assert "Can I carry keys on Shabbat?" in prompt

    @pytest.mark.asyncio
    async def test_voice_prompt_includes_history(self, mock_anthropic_client, mock_claude_response):
        agent = MetaRabbinicVoiceAgent(mock_anthropic_client)
        mock_anthropic_client.chat.completions.create.return_value = mock_claude_response(
            "A warm response."
        )
        context = AgentContext(
            user_message="What about the lenient view you mentioned?",
            conversation_history=HISTORY,
        )
        await agent.process(context)

        prompt = _sent_prompt(mock_anthropic_client)
        assert "CONVERSATION SO FAR" in prompt
        assert "Can I carry keys on Shabbat?" in prompt

    def test_voice_stream_prompt_includes_history(self, mock_anthropic_client):
        agent = MetaRabbinicVoiceAgent(mock_anthropic_client)
        mock_stream = MagicMock()
        mock_stream.__iter__ = MagicMock(return_value=iter([]))
        mock_anthropic_client.chat.completions.create.return_value = mock_stream

        context = AgentContext(
            user_message="What about the lenient view you mentioned?",
            conversation_history=HISTORY,
        )
        list(agent.process_stream(context))

        prompt = _sent_prompt(mock_anthropic_client)
        assert "CONVERSATION SO FAR" in prompt
        assert "Can I carry keys on Shabbat?" in prompt

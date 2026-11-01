"""Tests for agents/jev.py and the pastoral agent's Jev-first path."""

import json

import httpx
import pytest

from app.agents.base import AgentContext, AuthorityLevel, PastoralMode, ToneConstraint
from app.agents.jev import (
    CRISIS_THRESHOLD,
    QUESTIONS,
    JevPastoralClassifier,
    build_state,
    interpret_answers,
)
from app.agents.pastoral import PastoralContextAgent


def _answers(**overrides):
    """A calm, factual-question answer set; override fields per test."""
    answers = {
        "mode": {"type": "choice", "choice": "curiosity", "confidence": 0.95},
        "question_type": {"type": "choice", "choice": "factual", "confidence": 0.9},
        "tone": {"type": "choice", "choice": "exploratory", "confidence": 0.8},
        "authority_level": {"type": "choice", "choice": "definitive", "confidence": 0.8},
        "emotional_state": {"type": "choice", "choice": "curious", "confidence": 0.9},
        "vulnerable": {"type": "noul", "noul": 0.02},
        "needs_human_referral": {"type": "noul", "noul": 0.01},
        "risk_self_harm": {"type": "noul", "noul": 0.001},
        "risk_abuse": {"type": "noul", "noul": 0.001},
        "risk_acute_distress": {"type": "noul", "noul": 0.002},
    }
    for name, value in overrides.items():
        answers[name] = {**answers[name], **value}
    return answers


def _classifier(handler):
    return JevPastoralClassifier(api_key="sk-test", transport=httpx.MockTransport(handler))


def _jev_response(answers, cost=0.00003):
    return httpx.Response(200, json={
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 700, "output_tokens": 0, "cost": cost},
    })


class TestInterpretAnswers:
    def test_calm_factual_question(self):
        pc = interpret_answers(_answers()).pastoral_context
        assert pc.mode == PastoralMode.CURIOSITY
        assert pc.question_type == "factual"
        assert pc.vulnerability_detected is False
        assert pc.requires_human_referral is False
        assert pc.crisis_indicators == []
        assert pc.authority_level == AuthorityLevel.DEFINITIVE

    def test_risk_at_threshold_is_crisis(self):
        decision = interpret_answers(_answers(risk_self_harm={"noul": CRISIS_THRESHOLD}))
        pc = decision.pastoral_context
        assert pc.mode == PastoralMode.CRISIS
        assert pc.requires_human_referral is True
        assert pc.vulnerability_detected is True
        assert pc.tone == ToneConstraint.GENTLE
        assert pc.authority_level == AuthorityLevel.SUGGESTIVE
        assert pc.crisis_indicators == ["possible self-harm or suicidal thoughts"]
        assert pc.question_type == "personal"
        assert pc.emotional_state == "distressed"

    def test_crisis_mode_choice_alone_is_crisis(self):
        pc = interpret_answers(_answers(mode={"choice": "crisis", "confidence": 0.4})).pastoral_context
        assert pc.mode == PastoralMode.CRISIS
        assert pc.requires_human_referral is True

    def test_crisis_share_of_mode_is_crisis(self):
        pc = interpret_answers(_answers(mode={
            "choice": "counseling",
            "confidence": 0.7,
            "probabilities": {"teaching": 0.0, "counseling": 0.7, "crisis": 0.25, "curiosity": 0.05},
        })).pastoral_context
        assert pc.mode == PastoralMode.CRISIS

    def test_mismatched_answer_type_defers(self):
        assert interpret_answers(_answers(vulnerable={"type": "choice"})).pastoral_context is None

    def test_ambiguous_risk_defers_to_llm(self):
        decision = interpret_answers(_answers(risk_abuse={"noul": 0.1}))
        assert decision.pastoral_context is None
        assert "ambiguous crisis signal" in decision.fallback_reason

    def test_low_mode_confidence_defers_to_llm(self):
        decision = interpret_answers(_answers(mode={"confidence": 0.3}))
        assert decision.pastoral_context is None
        assert "low confidence" in decision.fallback_reason

    def test_missing_confidence_is_accepted(self):
        answers = _answers()
        del answers["mode"]["confidence"]
        pc = interpret_answers(answers).pastoral_context
        assert pc.mode == PastoralMode.CURIOSITY

    def test_vulnerable_person_never_gets_definitive_or_firm(self):
        pc = interpret_answers(_answers(
            vulnerable={"noul": 0.6},
            tone={"choice": "firm"},
        )).pastoral_context
        assert pc.vulnerability_detected is True
        assert pc.authority_level == AuthorityLevel.SUGGESTIVE
        assert pc.tone == ToneConstraint.GENTLE

    def test_referral_without_crisis(self):
        pc = interpret_answers(_answers(needs_human_referral={"noul": 0.7})).pastoral_context
        assert pc.requires_human_referral is True
        assert pc.mode == PastoralMode.CURIOSITY

    def test_missing_question_defers(self):
        answers = _answers()
        del answers["risk_abuse"]
        assert interpret_answers(answers).pastoral_context is None

    def test_unknown_label_defers(self):
        assert interpret_answers(_answers(tone={"choice": "sarcastic"})).pastoral_context is None


class TestBuildState:
    def test_includes_history_and_background(self):
        context = AgentContext(
            user_message="What about the lenient view?",
            conversation_history=[{"role": "user", "content": "x" * 500}],
            user_denomination="conservative",
            user_bio="Convert, two years in",
        )
        state = build_state(context)
        assert state["message"] == "What about the lenient view?"
        assert len(state["recent_conversation"][0]["content"]) == 200
        assert state["user_background"] == {"denomination": "conservative", "bio": "Convert, two years in"}

    def test_message_only(self):
        assert build_state(AgentContext(user_message="hi")) == {"message": "hi"}


class TestJevPastoralClassifier:
    async def test_sends_one_request_with_every_question(self):
        seen = []

        def handler(request):
            seen.append(request)
            return _jev_response(_answers())

        decision, metrics = await _classifier(handler).classify(AgentContext(user_message="What is Shabbat?"))

        assert len(seen) == 1
        body = json.loads(seen[0].content)
        assert body["model"] == "typesafe/jev-1.13"
        assert set(body["questions"]) == set(QUESTIONS)
        assert seen[0].headers["Authorization"] == "Bearer sk-test"
        assert decision.pastoral_context.mode == PastoralMode.CURIOSITY
        assert metrics.input_tokens == 700
        assert metrics.estimated_cost_usd == 0.00003

    async def test_http_error_falls_back(self):
        decision, metrics = await _classifier(lambda r: httpx.Response(503)).classify(
            AgentContext(user_message="hi"))
        assert decision.pastoral_context is None
        assert "request failed" in decision.fallback_reason
        assert metrics is None

    async def test_timeout_falls_back(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        decision, _ = await _classifier(handler).classify(AgentContext(user_message="hi"))
        assert decision.pastoral_context is None

    async def test_error_body_falls_back(self):
        decision, _ = await _classifier(lambda r: httpx.Response(200, json={"error": {"message": "x"}})).classify(
            AgentContext(user_message="hi"))
        assert decision.fallback_reason == "error response"

    async def test_missing_cost_is_estimated(self):
        def handler(request):
            return httpx.Response(200, json={"answers": _answers(), "usage": {"input_tokens": 1_000_000}})

        _, metrics = await _classifier(handler).classify(AgentContext(user_message="hi"))
        assert metrics.estimated_cost_usd == pytest.approx(0.042)


class TestPastoralAgentWithJev:
    @pytest.fixture
    def llm_crisis_response(self, mock_claude_response):
        return mock_claude_response(json.dumps({
            "mode": "crisis",
            "tone": "gentle",
            "authority_level": "exploratory",
            "vulnerability_detected": True,
            "crisis_indicators": ["hopelessness"],
            "emotional_state": "distressed",
            "requires_human_referral": True,
        }))

    async def test_jev_answer_skips_llm(self, mock_openai_client):
        agent = PastoralContextAgent(mock_openai_client, classifier=_classifier(lambda r: _jev_response(_answers())))

        context = await agent.process(AgentContext(user_message="What is Shabbat?"))

        mock_openai_client.chat.completions.create.assert_not_called()
        assert context.pastoral_context.mode == PastoralMode.CURIOSITY
        assert context.metadata["pastoral_classifier"] == "jev"
        assert context.agent_metrics["PastoralContextAgent"]["input_tokens"] == 700

    async def test_ambiguous_risk_uses_llm(self, mock_openai_client, llm_crisis_response):
        mock_openai_client.chat.completions.create.return_value = llm_crisis_response
        classifier = _classifier(lambda r: _jev_response(_answers(risk_acute_distress={"noul": 0.12})))
        agent = PastoralContextAgent(mock_openai_client, classifier=classifier)

        context = await agent.process(AgentContext(user_message="I don't know how much longer I can do this"))

        mock_openai_client.chat.completions.create.assert_called_once()
        assert context.pastoral_context.mode == PastoralMode.CRISIS
        assert context.metadata["pastoral_classifier"] == "llm"
        assert "ambiguous crisis signal" in context.metadata["pastoral_classifier_fallback"]
        # Both calls count toward the agent's cost.
        assert context.agent_metrics["PastoralContextAgent"]["input_tokens"] == 700 + 100

    async def test_jev_outage_uses_llm(self, mock_openai_client, llm_crisis_response):
        mock_openai_client.chat.completions.create.return_value = llm_crisis_response
        agent = PastoralContextAgent(mock_openai_client, classifier=_classifier(lambda r: httpx.Response(500)))

        context = await agent.process(AgentContext(user_message="I can't go on"))

        mock_openai_client.chat.completions.create.assert_called_once()
        assert context.pastoral_context.requires_human_referral is True

    async def test_no_classifier_uses_llm(self, mock_openai_client, llm_crisis_response):
        mock_openai_client.chat.completions.create.return_value = llm_crisis_response
        context = await PastoralContextAgent(mock_openai_client).process(AgentContext(user_message="hi"))
        assert context.metadata["pastoral_classifier"] == "llm"

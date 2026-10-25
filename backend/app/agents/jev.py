"""Jev-based pastoral classification -- a fast first pass for the pastoral agent.

Every field of a ``PastoralContext`` is a category or a boolean, which is
exactly what Jev (a decision model served by OpenRouter) answers. One Jev
request asks every pastoral question at once and returns typed answers in
a fraction of the time and cost of a full LLM call, removing one of the
sequential LLM calls that run before the user sees a reply.

Safety posture:
    Crisis detection is the reason this agent exists, so the thresholds
    below are deliberately biased toward recall -- a false alarm costs a
    gentler tone and a referral suggestion; a missed crisis costs far
    more. A message is a crisis when any risk question reaches
    ``CRISIS_THRESHOLD``, when Jev picks the crisis mode, or when the
    crisis mode merely gets that much probability. Any of these defers to
    the LLM agent instead of trusting Jev:

    - the request fails, times out, or returns an incomplete answer set;
    - a crisis signal is present but below ``CRISIS_THRESHOLD`` (the
      ambiguous band between ``CRISIS_REVIEW_THRESHOLD`` and
      ``CRISIS_THRESHOLD``);
    - Jev is unsure of the mode or question type.

Calibration:
    The thresholds are conservative starting points, not values measured
    on labeled data. Before relying on them, sweep each risk question's
    threshold on a labeled sample of real messages (OpenRouter's Jev
    cookbook suggests 100-200 items) and keep crisis recall as the
    deciding metric.

API reference:
    ``POST https://openrouter.ai/api/alpha/decisions`` with
    ``{"model", "state", "questions"}``; ``choice`` questions return
    ``answers[name].choice`` (+ optional ``confidence``), ``noul``
    questions return ``answers[name].noul`` (probability of "yes").
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from .base import (
    AgentContext,
    AuthorityLevel,
    LLMMetrics,
    PastoralContext,
    PastoralMode,
    ToneConstraint,
)

logger = logging.getLogger(__name__)

JEV_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"

# Used only when a response omits ``usage.cost``.
JEV_INPUT_COST_PER_MILLION = 0.042

# ---------------------------------------------------------------------------
# Thresholds (biased toward catching crises -- see module docstring)
# ---------------------------------------------------------------------------

# Any risk question at or above this probability is treated as a crisis.
CRISIS_THRESHOLD = 0.2
# Risk probabilities in [CRISIS_REVIEW_THRESHOLD, CRISIS_THRESHOLD) are
# ambiguous: the LLM agent re-assesses the message instead of Jev.
CRISIS_REVIEW_THRESHOLD = 0.05
# Low on purpose: "when in doubt, err on the side of gentleness".
VULNERABILITY_THRESHOLD = 0.35
REFERRAL_THRESHOLD = 0.5
# Below this confidence on mode or question type, the LLM decides.
MIN_CHOICE_CONFIDENCE = 0.5

# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

# Risk questions: name -> (crisis indicator label, instructions).
RISK_QUESTIONS = {
    "risk_self_harm": (
        "possible self-harm or suicidal thoughts",
        "Does `message` suggest the person may be thinking about suicide, "
        "self-harm, or not wanting to live -- whether stated directly or "
        "only hinted at?",
    ),
    "risk_abuse": (
        "possible abuse, coercion, or danger",
        "Does `message` suggest the person is being abused, threatened, "
        "coerced, or controlled, or is otherwise unsafe at home or in their "
        "community?",
    ),
    "risk_acute_distress": (
        "acute emotional distress",
        "Does `message` suggest the person is in acute emotional crisis -- "
        "overwhelming despair, panic, hopelessness, or feeling unable to cope?",
    ),
}

EMOTIONAL_STATES = {
    "curious": "Interested in learning; no distress expressed.",
    "neutral": "Matter-of-fact, no notable emotion.",
    "anxious": "Worried, fearful, or uncertain about something.",
    "grieving": "Mourning a death or another serious loss.",
    "ashamed": "Guilt, shame, or fear of being judged.",
    "doubting": "Struggling with faith, belief, or religious identity.",
    "lonely": "Isolated or disconnected from family or community.",
    "angry": "Frustrated or angry.",
    "distressed": "In pain, overwhelmed, or despairing.",
    "hopeful": "Optimistic, grateful, or joyful.",
}

QUESTIONS = {
    "mode": {
        "type": "choice",
        "instructions": (
            "How should a rabbi approach `message`? Choose counseling only "
            "when the person expresses a personal struggle or asks for "
            "personal guidance -- do not read emotional motives into "
            "intellectual questions."
        ),
        "criteria": {
            "teaching": "The person wants to learn or understand a topic, law, or text.",
            "counseling": "The person describes a personal struggle and wants guidance or support.",
            "crisis": "The person may be in danger or acute crisis and needs immediate care.",
            "curiosity": "A light, exploratory, or factual question asked out of interest.",
        },
    },
    "question_type": {
        "type": "choice",
        "instructions": (
            "What kind of question is `message`? When unsure between "
            "factual and personal, prefer factual."
        ),
        "criteria": {
            "factual": "Asks for facts, definitions, or explanations of concepts.",
            "historical": "Asks about historical events, speeches, figures, or timelines.",
            "halachic": "Asks about Jewish law or practice -- what is permitted or forbidden.",
            "personal": "Describes the person's own situation or struggle, or asks for emotional guidance.",
        },
    },
    "tone": {
        "type": "choice",
        "instructions": "Which tone should a rabbi's reply to `message` take?",
        "criteria": {
            "gentle": "Soft and caring -- the person is hurting or fragile.",
            "firm": "Clear and direct -- the person wants a straight answer and is not fragile.",
            "exploratory": "Open and inquisitive -- thinking through ideas together.",
            "validating": "Affirming -- the person needs to feel heard and accepted.",
        },
    },
    "authority_level": {
        "type": "choice",
        "instructions": "How authoritatively should a rabbi answer `message`?",
        "criteria": {
            "definitive": "A clear answer is appropriate and the person is not vulnerable.",
            "suggestive": "Offer guidance gently, leaving room for the person's own path.",
            "exploratory": "Present a range of views without steering toward one.",
        },
    },
    "emotional_state": {
        "type": "choice",
        "instructions": (
            "Which emotional state does `message` itself express? Judge only "
            "the current message, not `user_background`."
        ),
        "criteria": EMOTIONAL_STATES,
    },
    "vulnerable": {
        "type": "noul",
        "instructions": (
            "Does `message` show any sign the person is emotionally "
            "vulnerable -- distress, shame, grief, fear, doubt, or "
            "isolation -- even subtly?"
        ),
    },
    "needs_human_referral": {
        "type": "noul",
        "instructions": (
            "Would the person who wrote `message` be best served by speaking "
            "with a rabbi, counselor, or other professional in person?"
        ),
    },
    **{
        name: {"type": "noul", "instructions": instructions}
        for name, (_label, instructions) in RISK_QUESTIONS.items()
    },
}

_CHOICE_ENUMS = {
    "mode": PastoralMode,
    "tone": ToneConstraint,
    "authority_level": AuthorityLevel,
}


@dataclass
class JevDecision:
    """Outcome of interpreting a Jev response.

    Exactly one of ``pastoral_context`` or ``fallback_reason`` is set:
    a context means Jev's answer stands; a reason means the LLM agent
    should assess the message instead.
    """

    pastoral_context: Optional[PastoralContext] = None
    fallback_reason: Optional[str] = None


def build_state(context: AgentContext) -> dict:
    """Assemble the Jev ``state`` object from the pipeline context."""
    state = {"message": context.user_message}
    if context.conversation_history:
        state["recent_conversation"] = [
            {"role": msg.get("role"), "content": (msg.get("content") or "")[:200]}
            for msg in context.conversation_history[-3:]
        ]
    background = {}
    if context.user_denomination:
        background["denomination"] = context.user_denomination
    if context.user_bio:
        background["bio"] = context.user_bio
    if background:
        state["user_background"] = background
    return state


def interpret_answers(answers: dict) -> JevDecision:
    """Turn Jev answers into a ``PastoralContext``, or explain why not.

    Applies the crisis-first thresholds and the pastoral hard rules (a
    vulnerable person never gets a definitive or firm answer; a crisis
    always gets a gentle tone and a human referral).
    """
    try:
        for name, question in QUESTIONS.items():
            if answers[name].get("type", question["type"]) != question["type"]:
                raise ValueError(f"{name} answered as {answers[name]['type']}")
        choices = {name: answers[name]["choice"] for name in
                   ("mode", "question_type", "tone", "authority_level", "emotional_state")}
        confidences = {name: answers[name].get("confidence", 1.0) for name in ("mode", "question_type")}
        risks = {name: float(answers[name]["noul"]) for name in RISK_QUESTIONS}
        # Even when another mode wins, a sizeable "crisis" share counts.
        mode_crisis_p = float((answers["mode"].get("probabilities") or {}).get("crisis", 0.0))
        vulnerable_p = float(answers["vulnerable"]["noul"])
        referral_p = float(answers["needs_human_referral"]["noul"])
        mode = PastoralMode(choices["mode"])
        tone = ToneConstraint(choices["tone"])
        authority = AuthorityLevel(choices["authority_level"])
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return JevDecision(fallback_reason=f"incomplete or invalid answers ({e!r})")

    if choices["question_type"] not in QUESTIONS["question_type"]["criteria"]:
        return JevDecision(fallback_reason=f"unknown question_type {choices['question_type']!r}")

    max_risk = max(risks.values())
    crisis = (
        max_risk >= CRISIS_THRESHOLD
        or mode == PastoralMode.CRISIS
        or mode_crisis_p >= CRISIS_THRESHOLD
    )

    if not crisis and max_risk >= CRISIS_REVIEW_THRESHOLD:
        return JevDecision(fallback_reason=f"ambiguous crisis signal (max risk {max_risk:.2f})")
    if not crisis and min(confidences.values()) < MIN_CHOICE_CONFIDENCE:
        return JevDecision(fallback_reason=f"low confidence {confidences}")

    vulnerable = crisis or vulnerable_p >= VULNERABILITY_THRESHOLD
    emotional_state = choices["emotional_state"]
    question_type = choices["question_type"]

    if crisis:
        mode = PastoralMode.CRISIS
        tone = ToneConstraint.GENTLE
        question_type = "personal"
        if emotional_state in ("curious", "neutral", "hopeful"):
            emotional_state = "distressed"
    if vulnerable:
        if authority == AuthorityLevel.DEFINITIVE:
            authority = AuthorityLevel.SUGGESTIVE
        if tone == ToneConstraint.FIRM:
            tone = ToneConstraint.GENTLE

    return JevDecision(pastoral_context=PastoralContext(
        mode=mode,
        tone=tone,
        authority_level=authority,
        vulnerability_detected=vulnerable,
        crisis_indicators=[label for name, (label, _) in RISK_QUESTIONS.items()
                           if risks[name] >= CRISIS_THRESHOLD],
        emotional_state=emotional_state,
        requires_human_referral=crisis or referral_p >= REFERRAL_THRESHOLD,
        question_type=question_type,
    ))


class JevPastoralClassifier:
    """Classifies a message's pastoral context with a single Jev request."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_JEV_MODEL,
        url: str = JEV_DECISIONS_URL,
        timeout_seconds: float = 5.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.url = url
        self.timeout_seconds = timeout_seconds
        # Injected in tests; production uses httpx's default transport.
        self._transport = transport

    async def classify(self, context: AgentContext) -> tuple[JevDecision, Optional[LLMMetrics]]:
        """Ask Jev every pastoral question about the current message.

        Never raises: request or parsing failures become a fallback
        decision so the pastoral agent can use the LLM instead.

        Returns:
            ``(decision, metrics)`` -- *metrics* is ``None`` when no
            response was received.
        """
        body = {"model": self.model, "state": build_state(context), "questions": QUESTIONS}
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = await client.post(
                    self.url,
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            return JevDecision(fallback_reason=f"request failed ({e!r})"), None
        latency_ms = int((time.time() - start) * 1000)
        if not isinstance(data, dict) or data.get("error"):
            return JevDecision(fallback_reason="error response"), None

        metrics = LLMMetrics(latency_ms=latency_ms)
        try:
            usage = data.get("usage") or {}
            metrics.input_tokens = int(usage.get("input_tokens") or 0)
            metrics.output_tokens = int(usage.get("output_tokens") or 0)
            cost = usage.get("cost")
            if cost is None:
                cost = metrics.input_tokens / 1_000_000 * JEV_INPUT_COST_PER_MILLION
            metrics.estimated_cost_usd = round(float(cost), 6)
        except (AttributeError, TypeError, ValueError):
            logger.warning("Jev response has malformed usage; recording latency only")

        answers = data.get("answers")
        if not isinstance(answers, dict):
            return JevDecision(fallback_reason="response has no answers"), metrics
        return interpret_answers(answers), metrics

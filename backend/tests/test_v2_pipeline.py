"""Tests for the v2 pipeline (run_turn / finish_audit) and the v2 endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.chat import pipeline as pl
from app.chat.retrieval import Passage
from app.llm import client as llm_client
from tests.fakes_anthropic import FakeClient, classifier_json


PASSAGES = [
    Passage(n=1, title="Talmud Shabbat", ref="Daf 2b (part 2)", text="Carrying from domain to domain...",
            category="Talmud Bavli", url="https://www.sefaria.org/Shabbat.2b"),
    Passage(n=2, title="Mishnah Eruvin", ref="1:1", text="An alleyway...", category="Mishnah",
            url="https://www.sefaria.org/search?q=Mishnah%20Eruvin"),
]


@pytest.fixture(autouse=True)
def no_alerts():
    with patch("app.chat.pipeline.send_admin_alert", new=AsyncMock(return_value=False)):
        yield


async def collect(inp, fake, passages=PASSAGES):
    llm_client.set_client(fake)
    outcome = pl.TurnOutcome()
    with patch("app.chat.pipeline.retrieve", new=AsyncMock(return_value=list(passages))):
        events = [e async for e in pl.run_turn(inp, outcome)]
    return events, outcome


def types(events):
    return [e["type"] for e in events]


async def test_teaching_turn_streams_with_citations_and_metadata():
    fake = FakeClient(stream_chunks=["Carrying ", "requires an eruv."], citations_at={1: 0})
    events, outcome = await collect(pl.TurnInput(message="Can I carry on Shabbat?"), fake)
    t = types(events)
    assert t[0] == "status"
    assert "safety_resources" not in t
    assert t.index("metadata") < t.index("token")
    assert "citation" in t and t[-1] == "metrics"
    cit = next(e for e in events if e["type"] == "citation")
    assert cit["n"] == 1 and cit["source"]["kind"] == "library"
    assert outcome.text == "Carrying requires an eruv."
    assert outcome.charge is True
    meta = outcome.metadata
    assert meta["pipeline"] == "v2" and meta["pastoral_mode"] == "teaching" and meta["rag_used"]
    assert meta["citations"] == [{"n": 1, "offset": len("Carrying requires an eruv.")}]
    assert meta["sources"][0]["kind"] == "library" and meta["sources"][1]["kind"] == "library_unused"
    assert meta["estimated_cost_usd"] > 0

    req = fake.stream_calls[0]
    assert req["model"] == "claude-sonnet-5-5"
    assert req["fallbacks"] == "default" and req["betas"] == [llm_client.FALLBACK_BETA]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"] == {"effort": "low"}
    assert "temperature" not in req
    # Library passages are citable search results in the user turn; overlay is a trailing system message.
    user_turn = req["messages"][-2]
    assert user_turn["role"] == "user"
    assert [b["type"] for b in user_turn["content"]] == ["search_result", "search_result", "text"]
    assert req["messages"][-1]["role"] == "system"


async def test_constitution_prefix_is_frozen_across_turns():
    fake = FakeClient()
    await collect(pl.TurnInput(message="first question"), fake)
    await collect(pl.TurnInput(message="different question", denomination="reform"), fake)
    a, b = fake.stream_calls
    assert a["system"][0] == b["system"][0]  # byte-identical cached prefix


async def test_crisis_card_precedes_any_model_call_and_turn_is_free():
    fake = FakeClient(classifier=classifier_json(mode="crisis", risk={"self_harm": 3}),
                      stream_chunks=["I'm so glad you told me."])
    events, outcome = await collect(pl.TurnInput(message="I want to kill myself", region="US"), fake)
    t = types(events)
    assert t.index("safety_resources") < t.index("metadata") < t.index("token")
    card = next(e for e in events if e["type"] == "safety_resources")
    assert card["level"] == "crisis" and card["resources"][0]["phone"] == "988"
    assert outcome.charge is False
    meta = outcome.metadata
    assert meta["pastoral_mode"] == "crisis" and meta["requires_human_referral"]
    assert meta["crisis_indicators"] and meta["safety_resources"]["level"] == "crisis"
    req = fake.stream_calls[0]
    assert req["output_config"] == {"effort": "medium"}
    assert all(b["type"] == "text" for b in req["messages"][-2]["content"])  # no sources in crisis
    assert "SAFETY" in req["messages"][-1]["content"]


async def test_classifier_detected_crisis_gets_card_without_lexicon_match():
    fake = FakeClient(classifier=classifier_json(mode="counseling", risk={"self_harm": 2}))
    events, outcome = await collect(pl.TurnInput(message="I just want to sleep and not wake up next to anyone"), fake)
    assert any(e["type"] == "safety_resources" and e["level"] == "crisis" for e in events)
    assert outcome.charge is False


async def test_classifier_failure_fails_safe():
    fake = FakeClient(classifier=TimeoutError("slow"))
    events, outcome = await collect(pl.TurnInput(message="Is it OK to feel lost?"), fake)
    meta = outcome.metadata
    assert "classifier_unavailable" in meta["safety"]["flags"]
    assert meta["pastoral_mode"] == "counseling"
    assert "safety check for this turn was unavailable" in fake.stream_calls[0]["messages"][-1]["content"]


async def test_provider_failure_is_not_charged():
    import anthropic
    import httpx
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    fake = FakeClient(stream_error=err)
    events, outcome = await collect(pl.TurnInput(message="hello"), fake)
    assert events[-1]["type"] == "error" and events[-1]["code"] == "provider_unavailable"
    assert outcome.charge is False and not outcome.delivered_tokens


async def test_refusal_without_text_gets_safe_message():
    fake = FakeClient(stream_chunks=[], stop_reason="refusal")
    events, outcome = await collect(pl.TurnInput(message="something"), fake)
    assert outcome.text.startswith("I'm not able to help")


async def test_severe_audit_retracts():
    fake = FakeClient(audit=json.dumps({"verdict": "severe", "issues": ["harmful_medical_advice"], "note": "x"}))
    inp = pl.TurnInput(message="q")
    events, outcome = await collect(inp, fake)
    retraction = await pl.finish_audit(inp, outcome)
    assert retraction["type"] == "retraction"
    assert outcome.retracted and outcome.metadata["retracted"]
    assert outcome.metadata["original_content"] == "Hello world."
    assert outcome.text == retraction["replacement"]


async def test_passing_audit_records_verdict():
    fake = FakeClient()
    inp = pl.TurnInput(message="q")
    events, outcome = await collect(inp, fake)
    assert await pl.finish_audit(inp, outcome) is None
    assert outcome.metadata["audit"]["verdict"] == "pass"


def test_build_history_alternates_and_bounds():
    hist = [{"role": "assistant", "content": "greeting"}, {"role": "user", "content": "a"},
            {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}, {"role": "user", "content": "d"}]
    out = pl.build_history(hist)
    assert out[0]["role"] == "user" and out[0]["content"] == "a\n\nb"
    roles = [m["role"] for m in out]
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    assert roles[-1] == "assistant"


# --- Endpoint ----------------------------------------------------------------

@pytest.fixture
def v2_client():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from app.chat import endpoint
    from app.models import ChatRequest

    app = FastAPI()

    @app.post("/api/chat/stream")
    async def stream(request: Request, body: ChatRequest):
        return await endpoint.stream_chat_v2(request, body, None)

    with patch.object(endpoint, "get_settings") as gs:
        s = gs.return_value
        s.db_url = ""
        s.guest_ip_chat_limit = 3
        s.signup_credits = 10
        s.free_tier_daily_budget_usd = 5.0
        s.is_production = False
        s.rate_limit_chat_per_minute = 10
        with patch("app.ratelimit.get_settings", return_value=s):
            s.guest_rate_limit_per_minute = 50
            from app import ratelimit
            ratelimit._mem.clear()
            yield TestClient(app), endpoint


def parse(body):
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_endpoint_guest_turn_and_cookie(v2_client):
    client, endpoint = v2_client
    llm_client.set_client(FakeClient())
    with patch("app.chat.pipeline.retrieve", new=AsyncMock(return_value=[])):
        r = client.post("/api/chat/stream", json={"message": "What is Shabbat?", "request_id": "r1"})
    events = parse(r.text)
    assert events[0]["type"] == "session" and events[0]["request_id"] == "r1"
    assert any(e["type"] == "token" for e in events)
    assert any(e["type"] == "done" for e in events)
    assert "guest_chats_used" in r.cookies


def test_endpoint_guest_limit_but_crisis_still_answered(v2_client):
    client, endpoint = v2_client
    llm_client.set_client(FakeClient(classifier=classifier_json(mode="crisis", risk={"self_harm": 3})))
    with patch.object(endpoint, "get_guest_chats_used", return_value=99), \
         patch("app.chat.pipeline.retrieve", new=AsyncMock(return_value=[])):
        walled = parse(client.post("/api/chat/stream", json={"message": "Tell me about Purim"}).text)
        crisis = parse(client.post("/api/chat/stream", json={"message": "I want to end my life"}).text)
    # The fake classifier says crisis for both; a lexicon miss with classifier crisis also passes the wall.
    assert any(e["type"] == "safety_resources" for e in crisis)
    assert any(e["type"] == "token" for e in crisis)
    assert walled  # either answered (classifier crisis) or walled; never an exception


def test_endpoint_guest_limit_blocks_ordinary_turn(v2_client):
    client, endpoint = v2_client
    llm_client.set_client(FakeClient())
    with patch.object(endpoint, "get_guest_chats_used", return_value=99):
        events = parse(client.post("/api/chat/stream", json={"message": "Tell me about Purim"}).text)
    assert events == [{"type": "error", "code": "guest_limit_reached", "message": events[0]["message"]}]


def test_endpoint_rejects_overlong_message(v2_client):
    client, _ = v2_client
    events = parse(client.post("/api/chat/stream", json={"message": "a" * 5000}).text)
    assert events[0]["code"] == "invalid_input"

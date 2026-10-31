"""v2 chat pipeline: guardrails around one cached, streamed generation call.

Order of work for one turn (see docs/REWRITE_PLAN.md §2–3):

1. Lexicon floor (deterministic). A first-person crisis/abuse match sends the
   resource card immediately, before any model call.
2. Safety classifier (Haiku) **in parallel with** source retrieval.
3. Policy router (pure function) -> overlays, effort, card, charge.
4. Generation (Sonnet 5.5): frozen constitution (1h cache) + per-user
   profile block + history (auto-cached tail) + library passages as
   citable ``search_result`` blocks + a mid-conversation system overlay.
5. Post-stream audit (Haiku); a ``severe`` verdict retracts the answer.

``run_turn`` yields SSE event dicts (docs/API_CONTRACT_V2.md) and fills in
``TurnOutcome`` for the caller to persist and bill.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import anthropic

from ..config import get_settings
from ..llm.client import FALLBACK_BETA, get_client
from ..llm.pricing import usage_cost
from ..prompts import CONSTITUTION, PROMPT_VERSION, profile_block, turn_overlay
from ..safety import lexicon
from ..safety.alerts import send_admin_alert
from ..safety.audit import RETRACTION_TEXT, audit
from ..safety.classifier import ClassifierResult, classify
from ..safety.policy import TurnPolicy, decide
from ..safety.resources import build_card
from .retrieval import Passage, retrieve

logger = logging.getLogger(__name__)

HISTORY_TURNS = 20
HISTORY_CHARS = 6000  # per message, generous but bounded

_CRISIS_LABELS = {
    "self_harm": "possible self-harm or suicidal thoughts",
    "crisis_mode": "acute emotional crisis",
    "crisis_followup": "continuing crisis care",
    "abuse_disclosure": "possible abuse, coercion, or danger",
    "harm_to_others": "possible intent to harm others",
}


@dataclass
class TurnInput:
    message: str
    history: list[dict] = field(default_factory=list)  # [{role, content, metadata?}]
    denomination: Optional[str] = None
    bio: Optional[str] = None
    region: str = "US"
    is_guest: bool = False
    conversation_id: Optional[str] = None


@dataclass
class TurnOutcome:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    charge: bool = True
    delivered_tokens: bool = False
    retracted: bool = False
    failed: bool = False
    cost_usd: float = 0.0


def _prior_crisis(history: list[dict]) -> bool:
    for m in reversed(history[-4:]):
        meta = m.get("metadata") or {}
        if m.get("role") == "assistant" and meta.get("pastoral_mode") == "crisis":
            return True
        if m.get("role") == "user" and lexicon.scan(m.get("content", "")).forces_crisis:
            return True
    return False


def build_history(history: list[dict]) -> list[dict]:
    """Alternating user/assistant text turns, starting with a user turn."""
    out: list[dict] = []
    for m in history[-HISTORY_TURNS:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        content = content[:HISTORY_CHARS]
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":
        # The current message is appended separately; an unanswered prior
        # user turn (e.g. failed generation) is merged into context.
        out.append({"role": "assistant", "content": "(No reply was delivered to the previous message.)"})
    return out


def build_request(inp: TurnInput, policy: TurnPolicy, passages: list[Passage], *, overlay_as_system_message: bool = True) -> dict:
    settings = get_settings()
    system = [{"type": "text", "text": CONSTITUTION, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    profile = profile_block(inp.denomination, inp.bio)
    if profile:
        system.append({"type": "text", "text": profile})
    user_content: list[dict] = [p.search_result_block() for p in passages]
    user_content.append({"type": "text", "text": inp.message})
    overlay = turn_overlay(policy.overlays, policy.mode, policy.question_type)
    messages = build_history(inp.history) + [{"role": "user", "content": user_content}]
    if overlay_as_system_message:
        messages.append({"role": "system", "content": overlay})
    else:
        system.append({"type": "text", "text": overlay})
    return {
        "model": settings.generation_model,
        "max_tokens": settings.generation_max_tokens,
        "system": system,
        "messages": messages,
        "cache_control": {"type": "ephemeral"},
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": policy.effort},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def _metadata(policy: TurnPolicy, cls: ClassifierResult, passages: list[Passage], card: Optional[dict]) -> dict:
    meta = {
        "pipeline": "v2",
        "prompt_version": PROMPT_VERSION,
        "requires_human_referral": policy.requires_human_referral,
        "pastoral_mode": policy.mode,
        "question_type": cls.question_type,
        "vulnerability_detected": policy.vulnerability_detected,
        "emotional_state": cls.emotional_state,
        "moral_reconsideration": False,
        "rag_used": bool(passages),
        "sources": [p.to_source() for p in passages],
        "sources_cited": [f"{p.title}, {p.ref}" for p in passages],
        "safety": {"flags": policy.flags, "classifier": cls.to_metadata(), "card_level": policy.card_level},
    }
    indicators = [_CRISIS_LABELS[f] for f in policy.flags if f in _CRISIS_LABELS]
    if indicators:
        meta["crisis_indicators"] = indicators
    if card:
        meta["safety_resources"] = card
    return meta


async def run_turn(inp: TurnInput, outcome: TurnOutcome) -> AsyncIterator[dict]:
    settings = get_settings()
    t0 = time.monotonic()
    yield {"type": "status", "stage": "safety", "label": "Reading your question…"}

    # 1. Deterministic floor ------------------------------------------------
    lex = lexicon.scan(inp.message)
    card: Optional[dict] = None
    if lex.forces_crisis or lex.forces_abuse_protocol:
        card = build_card("crisis" if lex.forces_crisis else "abuse", inp.region)
        yield {"type": "safety_resources", **card}

    # 2. Classifier ∥ retrieval -------------------------------------------
    want_sources = not (lex.forces_crisis or lex.forces_abuse_protocol)
    cls_task = asyncio.create_task(classify(inp.message, inp.history))
    ret_task = asyncio.create_task(retrieve(inp.message)) if want_sources else None
    cls = await cls_task

    policy = decide(lex, cls, prior_crisis=_prior_crisis(inp.history),
                    effort_default=settings.generation_effort_default,
                    effort_care=settings.generation_effort_care)

    if policy.card_level and (card is None or card["level"] != policy.card_level):
        if not (card and card["level"] == "crisis"):
            card = build_card(policy.card_level, inp.region, youth=policy.youth)
            yield {"type": "safety_resources", **card}

    passages: list[Passage] = []
    if ret_task is not None:
        if policy.retrieve:
            yield {"type": "status", "stage": "sources", "label": "Looking in the sources…"}
            try:
                passages = await ret_task
                if cls.search_keywords:
                    extra = await retrieve(" ".join(cls.search_keywords))
                    known = {(p.title, p.ref) for p in passages}
                    for p in extra:
                        if (p.title, p.ref) not in known and len(passages) < 5:
                            passages.append(p)
                    for i, p in enumerate(passages, 1):
                        p.n = i
            except Exception as e:
                logger.warning("Retrieval failed: %s", e)
                passages = []
        else:
            ret_task.cancel()

    meta = _metadata(policy, cls, passages, card)
    outcome.charge = policy.charge
    outcome.metadata = meta
    # Classifier scores and flags stay server-side: exposing them would give
    # jailbreakers an oracle to tune prompts against.
    yield {"type": "metadata", "data": {k: v for k, v in meta.items() if k != "safety"}}

    alert_task = None
    if policy.alert_admin:
        # Fire now, await (bounded) after streaming: a slow webhook never delays care.
        alert_task = asyncio.create_task(send_admin_alert(
            "crisis" if policy.card_level == "crisis" else "safety", policy.flags, inp.conversation_id, inp.is_guest))

    # 3. Generation ---------------------------------------------------------
    yield {"type": "status", "stage": "writing", "label": "Writing…"}
    request = build_request(inp, policy, passages)
    gen_usage = None
    served_model = request["model"]
    citations: list[dict] = []
    cited: set[int] = set()
    text_parts: list[str] = []
    stop_reason = None
    gen_start = time.monotonic()
    first_token_ms = None

    async def _stream(req):
        nonlocal gen_usage, served_model, stop_reason, first_token_ms
        async with get_client().beta.messages.stream(**req) as stream:
            async for event in stream:
                etype = getattr(event, "type", "")
                if etype == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", "")
                    if dtype == "text_delta" and delta.text:
                        if first_token_ms is None:
                            first_token_ms = int((time.monotonic() - t0) * 1000)
                        text_parts.append(delta.text)
                        yield {"type": "token", "data": delta.text}
                    elif dtype == "citations_delta":
                        c = delta.citation
                        idx = getattr(c, "search_result_index", None)
                        if idx is not None and 0 <= idx < len(passages):
                            n = passages[idx].n
                            offset = sum(len(t) for t in text_parts)
                            if not citations or citations[-1]["n"] != n or citations[-1]["offset"] != offset:
                                citations.append({"n": n, "offset": offset})
                                cited.add(n)
                                yield {"type": "citation", "n": n, "source": passages[idx].to_source()}
            final = await stream.get_final_message()
            gen_usage = final.usage
            served_model = getattr(final, "model", served_model) or served_model
            stop_reason = final.stop_reason

    try:
        try:
            async for ev in _stream(request):
                outcome.delivered_tokens = outcome.delivered_tokens or ev["type"] == "token"
                yield ev
        except anthropic.BadRequestError as e:
            if text_parts or "system" not in str(e).lower():
                raise
            # Model/platform without mid-conversation system messages.
            logger.warning("Retrying with overlay in top-level system: %s", e)
            request = build_request(inp, policy, passages, overlay_as_system_message=False)
            async for ev in _stream(request):
                outcome.delivered_tokens = outcome.delivered_tokens or ev["type"] == "token"
                yield ev
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIStatusError) as e:
        logger.error("Generation failed: %s", e)
        outcome.failed = True
        outcome.charge = False  # never bill an answer that did not finish
        outcome.text = "".join(text_parts)
        if outcome.text:
            # Keep the partial answer (marked) so it is stored and audited like any other.
            meta["partial"] = True
            meta["citations"] = citations
        await _await_alert(alert_task)
        yield {"type": "error", "code": "provider_unavailable", "partial": bool(text_parts),
               "message": "The service is busy right now. Please try again in a moment."}
        return

    full_text = "".join(text_parts)
    if stop_reason == "refusal" and not full_text.strip():
        full_text = ("I'm not able to help with that request. If something is weighing on you, I'm glad to talk "
                     "about it in another way, and a rabbi or counselor you trust can help too.")
        yield {"type": "token", "data": full_text}
        outcome.delivered_tokens = True

    gen = usage_cost(served_model, gen_usage)
    gen.update({"latency_ms": int((time.monotonic() - gen_start) * 1000), "model": served_model,
                "stop_reason": stop_reason, "effort": policy.effort})
    cls_m = cls.metrics or {}
    total_cost = round(gen["estimated_cost_usd"] + cls_m.get("estimated_cost_usd", 0.0), 6)
    metrics = {
        "total_input_tokens": gen["input_tokens"] + gen["cache_read_tokens"] + gen["cache_write_tokens"] + cls_m.get("input_tokens", 0),
        "total_output_tokens": gen["output_tokens"] + cls_m.get("output_tokens", 0),
        "total_latency_ms": int((time.monotonic() - t0) * 1000),
        "time_to_first_token_ms": first_token_ms,
        "estimated_cost_usd": total_cost,
        "cache_read_tokens": gen["cache_read_tokens"],
        "cache_write_tokens": gen["cache_write_tokens"],
        "agent_metrics": {"classifier": cls_m, "generation": gen},
    }
    yield {"type": "metrics", "data": metrics}

    meta.update(metrics)
    meta["citations"] = citations
    meta["sources"] = [s for s in meta["sources"] if s["n"] in cited] + [
        {**s, "kind": "library_unused"} for s in meta["sources"] if s["n"] not in cited]
    outcome.text = full_text
    outcome.metadata = meta
    outcome.cost_usd = total_cost
    await _await_alert(alert_task)

    # 4. Audit (the caller emits `done` first, then calls finish_audit) -----


async def _await_alert(task) -> None:
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=3.0)
    except Exception as e:
        logger.warning("Admin alert did not complete: %s", e)


async def finish_audit(inp: TurnInput, outcome: TurnOutcome) -> Optional[dict]:
    """Run the post-stream audit; return a retraction event when severe."""
    if not outcome.text.strip():
        return None
    meta = outcome.metadata
    flags = meta.get("safety", {}).get("flags", [])
    result = await audit(inp.message, outcome.text, flags, meta.get("pastoral_mode", ""))
    meta["audit"] = result.to_metadata()
    a_cost = result.metrics.get("estimated_cost_usd", 0.0)
    meta["estimated_cost_usd"] = round(meta.get("estimated_cost_usd", 0.0) + a_cost, 6)
    meta.setdefault("agent_metrics", {})["audit"] = result.metrics
    outcome.cost_usd = meta["estimated_cost_usd"]
    if result.verdict == "severe":
        outcome.retracted = True
        meta["retracted"] = True
        meta["retraction_reason"] = ", ".join(result.issues) or "safety"
        meta["original_content"] = outcome.text
        outcome.text = RETRACTION_TEXT
        await send_admin_alert("retraction", result.issues, inp.conversation_id, inp.is_guest)
        return {"type": "retraction", "reason": "This answer was withdrawn by an automatic safety review.",
                "replacement": RETRACTION_TEXT}
    return None

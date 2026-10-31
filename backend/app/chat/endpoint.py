"""``POST /api/chat/stream`` for pipeline v2.

Responsibilities around ``pipeline.run_turn``: request validation, shared
rate limits, guest caps and the free-tier budget, credit charging through
the ledger (one charge per turn, automatic refund on failure or for crisis
turns), history
loading from the database, edit/regenerate, persistence, safety-event
logging, and the post-stream audit.

Walls never block a crisis turn: a first-person crisis/abuse lexicon match,
or a classifier crisis signal, proceeds free of charge even for a guest
over the limit or a user with no credits.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from .. import database as db
from .. import ratelimit
from ..auth import GUEST_FREE_CHAT_LIMIT, create_guest_chat_cookie, get_guest_chats_used
from ..config import get_settings
from ..models import ChatRequest
from ..safety import lexicon
from ..safety.classifier import classify
from ..safety.resources import region_for
from ..security import input_validator
from .pipeline import TurnInput, TurnOutcome, finish_audit, run_turn

logger = logging.getLogger(__name__)

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
GUEST_TURN_COST_ESTIMATE = 0.02


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _single(event: dict) -> StreamingResponse:
    return StreamingResponse(iter([sse(event)]), media_type="text/event-stream", headers=SSE_HEADERS)


def _err(code: str, message: str, detail: Optional[str] = None) -> StreamingResponse:
    ev = {"type": "error", "code": code, "message": message}
    if detail:
        ev["detail"] = detail
    return _single(ev)


def use_v2_for(user: Optional[dict], request: Request) -> bool:
    from ..llm.client import is_configured
    s = get_settings()
    if s.pipeline_version != "v2" or not is_configured():
        return False
    pct = max(0, min(100, s.pipeline_v2_rollout_percent))
    if pct >= 100:
        return True
    ident = user["id"] if user else ratelimit.client_ip(request)
    bucket = int(hashlib.sha256(ident.encode()).hexdigest()[:8], 16) % 100
    return bucket < pct


async def _crisis_override(message: str, history: list[dict]) -> bool:
    """Should a walled turn proceed anyway because the person may be in danger?"""
    lex = lexicon.scan(message)
    if lex.forces_crisis or lex.forces_abuse_protocol:
        return True
    cls = await classify(message, history)
    r = cls.risk
    return cls.mode == "crisis" or r["self_harm"] >= 2 or r["abuse_disclosure"] >= 2


async def stream_chat_v2(request: Request, body: ChatRequest, user: Optional[dict]) -> StreamingResponse:
    settings = get_settings()
    has_db = bool(settings.db_url)
    ip = ratelimit.client_ip(request)
    request_id = (body.request_id or str(uuid.uuid4()))[:64]
    # Billing key is server-generated: a client-chosen id must never let a
    # reused id skip the charge. Failed turns are refunded automatically, so
    # a client retry after a failure is not double-charged.
    charge_ref = f"{user['id'] if user else 'guest'}:{uuid.uuid4()}"

    # --- Abuse controls ------------------------------------------------------
    if await ratelimit.is_blocked(ip):
        return _err("access_restricted", "Too many unusual requests from your network. Please try again later.")
    if not await ratelimit.check_chat_rate(request, user["id"] if user else None):
        return _err("rate_limited", "You're sending messages quickly. Please wait a moment and try again.",
                    detail="retry_after=30")

    ok, problem = input_validator.validate_message(body.message)
    if not ok:
        return _err("invalid_input", problem or "Invalid message")
    message = input_validator.sanitize_message(body.message)
    if not message:
        return _err("invalid_input", "Message cannot be empty")

    # --- Conversation & history --------------------------------------------
    conversation_id = body.conversation_id
    history: list[dict] = []
    denomination = bio = None
    if user and has_db:
        if conversation_id:
            conv = await db.get_conversation(conversation_id, user["id"])
            if not conv:
                return _err("invalid_input", "Conversation not found")
            if body.edit_message_id:
                await db.delete_messages_from(conversation_id, body.edit_message_id, inclusive=True)
            msgs = await db.get_messages(conversation_id, limit=500)
            if body.regenerate:
                # Drop trailing assistant reply and the user message it answered.
                while msgs and msgs[-1]["role"] == "assistant":
                    await db.delete_messages_from(conversation_id, msgs[-1]["id"], inclusive=True)
                    msgs.pop()
                if msgs and msgs[-1]["role"] == "user":
                    await db.delete_messages_from(conversation_id, msgs[-1]["id"], inclusive=True)
                    msgs.pop()
            history = [{"role": m["role"], "content": m["content"], "metadata": m.get("metadata") or {}}
                       for m in msgs[-20:]]
        try:
            profile = await db.get_user_profile(user["id"])
            if profile:
                denomination, bio = profile.get("denomination"), profile.get("bio")
        except Exception as e:
            logger.warning("Profile unavailable: %s", e)
    else:
        history = [{"role": m.role, "content": m.content} for m in body.conversation_history[-20:]]

    # --- Walls (never for crisis turns) --------------------------------------
    is_guest_turn = False
    guest_count = 0
    charged_balance: Optional[int] = None
    charged = False
    if not user:
        guest_count = max(get_guest_chats_used(request), 0)
        ip_count = await ratelimit.guest_ip_count(request)
        over = guest_count >= GUEST_FREE_CHAT_LIMIT or ip_count >= settings.guest_ip_chat_limit * 2
        if not over and has_db:
            try:
                over = await db.get_free_tier_spend_today() >= settings.free_tier_daily_budget_usd
            except Exception:
                pass
        if over and not await _crisis_override(message, history):
            return _err("guest_limit_reached", "Sign in to keep the conversation going — new accounts get "
                        f"{settings.signup_credits} free messages.")
        is_guest_turn = not over
    elif has_db:
        try:
            charged_balance = await db.try_charge_credits(user["id"], 1, "chat", charge_ref)
        except Exception as e:
            logger.warning("Credit check failed: %s", e)
            return _err("internal", "Unable to verify your credits right now. Please try again in a moment.")
        if charged_balance is None:
            if not await _crisis_override(message, history):
                return _err("no_credits", "You're out of messages. Add more to continue — your draft is saved.")
        else:
            charged = True

    if user and has_db and conversation_id:
        try:
            await db.add_message(conversation_id, "user", message)
        except Exception as e:
            logger.warning("Could not save user message: %s", e)

    inp = TurnInput(
        message=message, history=history, denomination=denomination, bio=bio,
        region=region_for(body.client_tz, request.headers.get("accept-language")),
        is_guest=not user, conversation_id=conversation_id,
    )
    session_id = body.session_id or str(uuid.uuid4())

    async def refund():
        nonlocal charged
        if charged and user and has_db:
            try:
                await db.refund_credits(user["id"], 1, charge_ref)
                charged = False
            except Exception as e:
                logger.warning("Refund failed: %s", e)

    async def events():
        outcome = TurnOutcome()
        yield sse({"type": "session", "session_id": session_id, "conversation_id": conversation_id,
                   "request_id": request_id})
        try:
            async for ev in run_turn(inp, outcome):
                yield sse(ev)
                if ev.get("type") == "error":
                    await refund()
                    return
        except asyncio.CancelledError:
            if not outcome.delivered_tokens:
                await refund()
            raise
        except Exception as e:
            logger.exception("v2 stream failed")
            if not outcome.delivered_tokens:
                await refund()
            if has_db:
                try:
                    await db.log_error(error_type="llm_error", error_message=str(e)[:2000],
                                       user_id=user["id"] if user else None, conversation_id=conversation_id,
                                       request_context={"pipeline": "v2", "request_id": request_id})
                except Exception:
                    pass
            yield sse({"type": "error", "code": "internal",
                       "message": "Something went wrong while generating a response. Please try again."})
            return

        if not outcome.charge:
            await refund()  # crisis turns are free

        message_id = None
        if user and has_db and conversation_id and outcome.text:
            try:
                saved = await db.add_message(conversation_id, "assistant", outcome.text, outcome.metadata)
                message_id = saved.get("id") if saved else None
                if message_id:
                    yield sse({"type": "message_saved", "message_id": message_id})
            except Exception as e:
                logger.warning("Could not save assistant message: %s", e)
                yield sse({"type": "message_save_failed"})
            try:
                conv = await db.get_conversation(conversation_id, user["id"])
                if conv and not conv.get("title"):
                    title = await db.generate_conversation_title(conversation_id)
                    if title:
                        await db.update_conversation(conversation_id, user["id"], title)
            except Exception as e:
                logger.warning("Could not set title: %s", e)

        credits_left = None
        if user and has_db:
            try:
                credits_left = await db.get_user_credits(user["id"])
            except Exception:
                pass
        yield sse({"type": "done", "message_id": message_id, "credits_remaining": credits_left, "charged": charged})

        # Post-stream audit; may retract.
        try:
            retraction = await finish_audit(inp, outcome)
        except Exception as e:
            logger.warning("Audit failed: %s", e)
            retraction = None
        if retraction:
            yield sse({**retraction, "message_id": message_id})
        if user and has_db and message_id:
            try:
                await db.update_message(message_id, outcome.text, outcome.metadata)
            except Exception as e:
                logger.warning("Could not store audit: %s", e)

        # Safety log and spend accounting.
        safety = outcome.metadata.get("safety", {})
        audit_verdict = outcome.metadata.get("audit", {}).get("verdict")
        kinds = []
        if safety.get("card_level") in ("crisis", "abuse"):
            kinds.append(safety["card_level"])
        if "harm_to_others" in safety.get("flags", []):
            kinds.append("harm")
        if audit_verdict in ("concern", "severe"):
            kinds.append(f"audit_{audit_verdict}")
        if "manipulation_attempt" in safety.get("flags", []):
            kinds.append("manipulation")
            await ratelimit.add_penalty(ratelimit.client_ip(request))
        if has_db:
            for kind in kinds:
                try:
                    await db.record_safety_event(kind, safety.get("flags", []), safety.get("card_level"),
                                                 user["id"] if user else None, conversation_id, message_id, not user)
                except Exception as e:
                    logger.warning("Could not record safety event: %s", e)
            if not user:
                try:
                    await db.add_free_tier_spend(outcome.cost_usd or GUEST_TURN_COST_ESTIMATE)
                except Exception:
                    pass

    response = StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
    if is_guest_turn:
        response.set_cookie("guest_chats_used", create_guest_chat_cookie(guest_count + 1), httponly=True,
                            secure=settings.is_production, samesite="lax", max_age=86400 * 365, path="/")
        await ratelimit.record_guest_turn(request)
    return response

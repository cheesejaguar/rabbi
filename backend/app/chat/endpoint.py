"""``POST /api/chat/stream`` for pipeline v2.

Responsibilities around ``pipeline.run_turn``: request validation, shared
rate limits, guest caps and the free-tier budget, credit charging through
the ledger (one charge per turn, automatic refund on failure, abort before
any text, or crisis turns), history loading from the database,
edit/regenerate, persistence, safety-event logging, and the post-stream
audit.

Crisis floor first: the lexicon runs before any other check, so no early
exit (rate limit, block, overlong input, walls, credit errors) can stop a
person who may be in danger from seeing crisis resources. Walls are lifted
for crisis turns, which are free.
"""

import hashlib
import json
import logging
import uuid
from typing import Optional

import anyio
from fastapi import Request
from fastapi.responses import StreamingResponse

from .. import database as db
from .. import ratelimit
from ..auth import GUEST_FREE_CHAT_LIMIT, create_guest_chat_cookie, get_guest_chats_used
from ..config import get_settings
from ..models import ChatRequest
from ..safety import lexicon
from ..safety.classifier import classify
from ..safety.policy import decide
from ..safety.resources import build_card, region_for
from ..security import MAX_MESSAGE_LENGTH, input_validator
from .pipeline import TurnInput, TurnOutcome, _prior_crisis, finish_audit, run_turn

logger = logging.getLogger(__name__)

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
GUEST_TURN_COST_ESTIMATE = 0.02


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _stream(events: list[dict]) -> StreamingResponse:
    return StreamingResponse(iter([sse(e) for e in events]), media_type="text/event-stream", headers=SSE_HEADERS)


def _err(code: str, message: str, detail: Optional[str] = None, card: Optional[dict] = None) -> StreamingResponse:
    """An error response; a crisis card (when the floor matched) always comes first."""
    ev = {"type": "error", "code": code, "message": message}
    if detail:
        ev["detail"] = detail
    events = ([{"type": "safety_resources", **card}] if card else []) + [ev]
    return _stream(events)


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


async def _crisis_override(lex: lexicon.LexiconResult, message: str, history: list[dict]) -> bool:
    """Should a walled turn proceed anyway because the person may be in danger?

    Uses the same policy the pipeline uses (including crisis follow-ups), and
    errs open when the classifier is unavailable on a sensitive topic.
    """
    if lex.forces_crisis or lex.forces_abuse_protocol:
        return True
    cls = await classify(message, history)
    policy = decide(lex, cls, prior_crisis=_prior_crisis(history))
    if policy.is_crisis:
        return True
    return not cls.available and (lex.self_harm == "topic" or _prior_crisis(history))


async def _shielded(coro) -> None:
    """Run cleanup to completion even if the client disconnects (anyio re-cancels at every await)."""
    with anyio.CancelScope(shield=True):
        try:
            await coro
        except Exception as e:
            logger.warning("Shielded cleanup failed: %s", e)


async def stream_chat_v2(request: Request, body: ChatRequest, user: Optional[dict]) -> StreamingResponse:
    settings = get_settings()
    has_db = bool(settings.db_url)
    ip = ratelimit.client_ip(request)
    request_id = (body.request_id or str(uuid.uuid4()))[:64]
    # Billing key is server-generated: a client-chosen id must never let a
    # reused id skip the charge.
    charge_ref = f"{user['id'] if user else 'guest'}:{uuid.uuid4()}"
    region = region_for(body.client_tz, request.headers.get("accept-language"))

    # --- Crisis floor before anything else ------------------------------------
    lex = lexicon.scan(body.message or "")
    floor = lex.forces_crisis or lex.forces_abuse_protocol
    floor_card = build_card("crisis" if lex.forces_crisis else "abuse", region) if floor else None

    # --- Abuse controls (bypassed for crisis turns) ---------------------------
    if not floor:
        if not user and await ratelimit.is_blocked(ip):
            return _err("access_restricted", "Too many unusual requests from your network. Please try again later.")
        if not await ratelimit.check_chat_rate(request, user["id"] if user else None):
            return _err("rate_limited", "You're sending messages quickly. Please wait a moment and try again.",
                        detail="retry_after=30")

    raw = body.message or ""
    if floor and len(raw) > MAX_MESSAGE_LENGTH:
        raw = raw[-MAX_MESSAGE_LENGTH:]  # keep the end, where the disclosure usually is
    ok, problem = input_validator.validate_message(raw)
    if not ok:
        return _err("invalid_input", problem or "Invalid message", card=floor_card)
    message = input_validator.sanitize_message(raw)
    if not message:
        return _err("invalid_input", "Message cannot be empty", card=floor_card)

    # --- Conversation & history (no mutation yet) -------------------------------
    conversation_id = body.conversation_id
    history: list[dict] = []
    denomination = bio = None
    delete_from_id: Optional[str] = None
    if user and has_db and conversation_id:
        conv = await db.get_conversation(conversation_id, user["id"])
        if not conv:
            return _err("invalid_input", "Conversation not found", card=floor_card)
        msgs = await db.get_recent_messages(conversation_id, limit=60)
        if body.edit_message_id:
            ids = [m["id"] for m in msgs]
            if body.edit_message_id in ids:
                msgs = msgs[:ids.index(body.edit_message_id)]
            delete_from_id = body.edit_message_id
        elif body.regenerate:
            # Drop the trailing assistant reply(ies) and the user message they answered.
            cut = len(msgs)
            while cut and msgs[cut - 1]["role"] == "assistant":
                cut -= 1
            if cut and msgs[cut - 1]["role"] == "user":
                cut -= 1
            if cut < len(msgs):
                delete_from_id = msgs[cut]["id"]
            msgs = msgs[:cut]
        history = [{"role": m["role"], "content": m["content"], "metadata": m.get("metadata") or {}}
                   for m in msgs[-20:]]
    else:
        history = [{"role": m.role, "content": m.content} for m in body.conversation_history[-20:]]
    if user and has_db:
        try:
            profile = await db.get_user_profile(user["id"])
            if profile:
                denomination, bio = profile.get("denomination"), profile.get("bio")
        except Exception as e:
            logger.warning("Profile unavailable: %s", e)

    # --- Walls (never for crisis turns) ---------------------------------------
    is_guest_turn = False
    guest_count = 0
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
        if over and not await _crisis_override(lex, message, history):
            return _err("guest_limit_reached", "Sign in to keep the conversation going — new accounts get "
                        f"{settings.signup_credits} free messages.")
        is_guest_turn = not over
    elif has_db:
        try:
            balance = await db.try_charge_credits(user["id"], 1, "chat", charge_ref)
        except Exception as e:
            logger.warning("Credit check failed: %s", e)
            if not await _crisis_override(lex, message, history):
                return _err("internal", "Unable to verify your credits right now. Please try again in a moment.")
            balance = None
        if balance is None:
            if not await _crisis_override(lex, message, history):
                return _err("no_credits", "You're out of messages. Add more to continue — your draft is saved.")
        else:
            charged = True

    # Edit/regenerate only mutate history once the turn is allowed to run.
    user_message_id: Optional[str] = None
    if user and has_db and conversation_id:
        try:
            if delete_from_id:
                await db.delete_messages_from(conversation_id, delete_from_id, inclusive=True)
            saved_user = await db.add_message(conversation_id, "user", message)
            user_message_id = (saved_user or {}).get("id")
        except Exception as e:
            logger.warning("Could not update conversation: %s", e)

    inp = TurnInput(message=message, history=history, denomination=denomination, bio=bio, region=region,
                    is_guest=not user, conversation_id=conversation_id)
    session_id = body.session_id or str(uuid.uuid4())

    async def refund():
        nonlocal charged
        if charged and user and has_db:
            await db.refund_credits(user["id"], 1, charge_ref)
            charged = False

    async def record_safety(outcome: TurnOutcome, message_id: Optional[str], kinds: list[str]):
        if not has_db:
            return
        safety = outcome.metadata.get("safety", {})
        for kind in kinds:
            await db.record_safety_event(kind, safety.get("flags", []), safety.get("card_level"),
                                         user["id"] if user else None, conversation_id, message_id, not user)

    async def save_and_audit(outcome: TurnOutcome, message_id: Optional[str]) -> Optional[dict]:
        """Audit the answer and persist the result. Shielded by callers."""
        retraction = await finish_audit(inp, outcome)
        if user and has_db and message_id:
            await db.update_message(message_id, outcome.text, outcome.metadata)
        verdict = outcome.metadata.get("audit", {}).get("verdict")
        if verdict in ("concern", "severe"):
            await record_safety(outcome, message_id, [f"audit_{verdict}"])
        return retraction

    async def events():
        outcome = TurnOutcome()
        finished = False
        try:
            yield sse({"type": "session", "session_id": session_id, "conversation_id": conversation_id,
                       "request_id": request_id, "user_message_id": user_message_id})
            errored = False
            async for ev in run_turn(inp, outcome):
                if ev.get("type") == "error":
                    errored = True
                yield sse(ev)
            if errored or not outcome.charge:
                await _shielded(refund())  # provider failure, or a free crisis turn

            message_id = None
            if user and has_db and conversation_id and outcome.text:
                try:
                    saved = await db.add_message(conversation_id, "assistant", outcome.text, outcome.metadata)
                    message_id = saved.get("id") if saved else None
                    if message_id:
                        yield sse({"type": "message_saved", "message_id": message_id,
                                   "user_message_id": user_message_id})
                except Exception as e:
                    logger.warning("Could not save assistant message: %s", e)
                    yield sse({"type": "message_save_failed"})
                if not errored:
                    try:
                        conv = await db.get_conversation(conversation_id, user["id"])
                        if conv and not conv.get("title"):
                            title = await db.generate_conversation_title(conversation_id)
                            if title:
                                await db.update_conversation(conversation_id, user["id"], title)
                    except Exception as e:
                        logger.warning("Could not set title: %s", e)

            # Record safety events and spend *before* `done`, so a client that
            # disconnects on `done` cannot skip them.
            safety = outcome.metadata.get("safety", {})
            kinds = []
            if safety.get("card_level") in ("crisis", "abuse"):
                kinds.append(safety["card_level"])
            if "harm_to_others" in safety.get("flags", []):
                kinds.append("harm")
            if "manipulation_attempt" in safety.get("flags", []):
                kinds.append("manipulation")
                if not user:  # never penalize a shared IP for one signed-in account
                    await _shielded(ratelimit.add_penalty(ip))
            await _shielded(record_safety(outcome, message_id, kinds))
            if not user and has_db and outcome.text:
                await _shielded(db.add_free_tier_spend(outcome.cost_usd or GUEST_TURN_COST_ESTIMATE))

            credits_left = None
            if user and has_db:
                try:
                    credits_left = await db.get_user_credits(user["id"])
                except Exception:
                    pass
            if not errored:
                yield sse({"type": "done", "message_id": message_id, "credits_remaining": credits_left,
                           "charged": charged})
            finished = True

            # Post-stream audit, shielded so a disconnect cannot skip it.
            retraction = None
            if outcome.text:
                with anyio.CancelScope(shield=True):
                    try:
                        retraction = await save_and_audit(outcome, message_id)
                    except Exception as e:
                        logger.warning("Audit failed: %s", e)
            if retraction:
                yield sse({**retraction, "message_id": message_id})
        except Exception as e:
            logger.exception("v2 stream failed")
            if has_db:
                await _shielded(db.log_error(error_type="llm_error", error_message=str(e)[:2000],
                                             user_id=user["id"] if user else None, conversation_id=conversation_id,
                                             request_context={"pipeline": "v2", "request_id": request_id}))
            if not finished:
                yield sse({"type": "error", "code": "internal",
                           "message": "Something went wrong while generating a response. Please try again."})
        finally:
            # Covers CancelledError (client abort) and GeneratorExit (closed at a yield):
            # no text delivered means no charge.
            if not finished and not outcome.delivered_tokens:
                await _shielded(refund())

    response = StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
    if is_guest_turn:
        response.set_cookie("guest_chats_used", create_guest_chat_cookie(guest_count + 1), httponly=True,
                            secure=settings.is_production, samesite="lax", max_age=86400 * 365, path="/")
        await ratelimit.record_guest_turn(request)
    return response

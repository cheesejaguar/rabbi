"""Admin API router for platform monitoring and moderation.

All endpoints require an authenticated administrator. Admin status is
granted two ways:

1. **Config bootstrap**: emails listed in the ``ADMIN_EMAILS`` setting
   (default: the platform owner) are always admins and are promoted in
   the database at startup / on login.
2. **Runtime grant**: an existing admin can promote or demote other
   users via ``POST /api/admin/users/{user_id}/role``. The flag is
   stored on the ``users.is_admin`` column.

Every mutation — and every moderation view of user conversation content —
is recorded in the ``admin_audit_log`` table so privileged access is
accountable.

Endpoint summary:
    - ``GET  /api/admin/overview``      -- platform health/usage/revenue counters
    - ``GET  /api/admin/users``          -- searchable, paginated user list
    - ``POST /api/admin/users/{id}/credits`` -- grant/deduct credits
    - ``POST /api/admin/users/{id}/role``    -- grant/revoke admin
    - ``GET  /api/admin/users/{id}/conversations`` -- a user's conversations
    - ``GET  /api/admin/conversations/{id}``       -- full conversation review
    - ``GET  /api/admin/flagged``        -- crisis / human-referral review queue
    - ``GET  /api/admin/feedback``       -- thumbs-down review queue
    - ``GET  /api/admin/errors``         -- error log browser (+ daily stats)
    - ``GET  /api/admin/purchases``      -- purchases across all users
    - ``GET  /api/admin/analytics``      -- sessions/referrers/devices/TTS stats
    - ``GET  /api/admin/costs``          -- estimated LLM spend per day
    - ``GET  /api/admin/audit-log``      -- trail of admin actions
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from typing import Optional

from .config import get_settings
from .auth import get_current_user
from . import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin(request: Request) -> dict:
    """FastAPI dependency that enforces administrator access.

    Config-listed admin emails are always accepted (bootstrap path, works
    even before the database row exists). Otherwise the ``users.is_admin``
    flag is checked.

    Args:
        request: The incoming FastAPI ``Request`` object.

    Returns:
        The authenticated admin's user dict.

    Raises:
        HTTPException: 401 if not authenticated, 403 if not an admin,
            500 if the admin check cannot be performed.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    email = (user.get("email") or "").lower()
    if email in settings.admin_email_list:
        return user

    if settings.db_url:
        try:
            if await db.is_user_admin(user["id"]):
                return user
        except Exception as e:
            logger.error(f"Admin check failed: {e}")
            raise HTTPException(status_code=500, detail="Could not verify admin access")

    raise HTTPException(status_code=403, detail="Admin access required")


def _require_db():
    """Raise 503 when no database is configured (admin tools need one)."""
    if not settings.db_url:
        raise HTTPException(status_code=503, detail="Database not configured")


class CreditAdjustment(BaseModel):
    """Request body for adjusting a user's credit balance.

    Attributes:
        delta: Credits to add (positive) or deduct (negative). Zero is
            rejected; magnitude is capped to prevent typos from granting
            enormous balances.
        reason: Free-text justification recorded in the audit log.
    """
    delta: int = Field(..., ge=-10000, le=10000)
    reason: str = Field(..., min_length=1, max_length=500)


class RoleUpdate(BaseModel):
    """Request body for granting or revoking administrator access."""
    is_admin: bool


@router.get("/overview")
async def get_overview(admin: dict = Depends(require_admin)):
    """Return platform-wide usage, revenue, error, and feedback counters."""
    _require_db()
    try:
        overview = await db.admin_get_overview()
        return {"overview": overview}
    except Exception as e:
        logger.error(f"Error building admin overview: {e}")
        raise HTTPException(status_code=500, detail="Failed to load overview")


@router.get("/users")
async def list_users(
    admin: dict = Depends(require_admin),
    search: Optional[str] = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List users with activity and spend rollups; optional search."""
    _require_db()
    try:
        users = await db.admin_list_users(search=search, limit=limit, offset=offset)
        total = await db.admin_count_users(search=search)
        return {"users": users, "total": total}
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.post("/users/{user_id}/credits")
async def adjust_credits(
    user_id: str,
    body: CreditAdjustment,
    admin: dict = Depends(require_admin),
):
    """Grant or deduct credits for a user, with an audited reason."""
    _require_db()
    if body.delta == 0:
        raise HTTPException(status_code=400, detail="delta must be non-zero")
    try:
        new_balance = await db.admin_adjust_credits(user_id, body.delta)
        if new_balance is None:
            raise HTTPException(status_code=404, detail="User not found")
        await db.log_admin_action(
            admin_user_id=admin["id"],
            action="adjust_credits",
            target_user_id=user_id,
            details={"delta": body.delta, "reason": body.reason, "new_balance": new_balance},
        )
        return {"success": True, "credits": new_balance}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adjusting credits for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to adjust credits")


@router.post("/users/{user_id}/role")
async def set_role(
    user_id: str,
    body: RoleUpdate,
    admin: dict = Depends(require_admin),
):
    """Grant or revoke administrator access for a user."""
    _require_db()
    # Admins cannot demote themselves - prevents locking everyone out.
    if user_id == admin["id"] and not body.is_admin:
        raise HTTPException(status_code=400, detail="Cannot revoke your own admin access")
    try:
        result = await db.admin_set_role(user_id, body.is_admin)
        if result is None:
            raise HTTPException(status_code=404, detail="User not found")
        await db.log_admin_action(
            admin_user_id=admin["id"],
            action="set_role",
            target_user_id=user_id,
            details={"is_admin": body.is_admin},
        )
        return {"success": True, "user": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting role for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update role")


@router.get("/users/{user_id}/conversations")
async def list_user_conversations(
    user_id: str,
    admin: dict = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List a user's conversations for moderation (audited)."""
    _require_db()
    try:
        conversations = await db.admin_list_user_conversations(user_id, limit=limit, offset=offset)
        await db.log_admin_action(
            admin_user_id=admin["id"],
            action="view_user_conversations",
            target_user_id=user_id,
            details={"count": len(conversations)},
        )
        return {"conversations": conversations}
    except Exception as e:
        logger.error(f"Error listing conversations for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to list conversations")


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    admin: dict = Depends(require_admin),
):
    """Fetch a full conversation with messages for moderation (audited)."""
    _require_db()
    try:
        conversation = await db.admin_get_conversation_with_messages(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        await db.log_admin_action(
            admin_user_id=admin["id"],
            action="view_conversation",
            target_user_id=conversation.get("user_id"),
            details={"conversation_id": conversation_id},
        )
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch conversation")


@router.get("/flagged")
async def list_flagged(
    admin: dict = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Crisis / human-referral review queue.

    Surfaces assistant messages whose pipeline metadata flagged a crisis,
    vulnerability, or human-referral recommendation.
    """
    _require_db()
    try:
        flagged = await db.admin_list_flagged_messages(limit=limit, offset=offset)
        return {"flagged": flagged}
    except Exception as e:
        logger.error(f"Error listing flagged messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to list flagged messages")


@router.get("/feedback")
async def list_feedback(
    admin: dict = Depends(require_admin),
    feedback_type: Optional[str] = Query(None, pattern="^(thumbs_up|thumbs_down)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Review queue of message ratings joined with rated content."""
    _require_db()
    try:
        feedback = await db.admin_list_feedback(
            feedback_type=feedback_type, limit=limit, offset=offset
        )
        return {"feedback": feedback}
    except Exception as e:
        logger.error(f"Error listing feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to list feedback")


@router.get("/errors")
async def list_errors(
    admin: dict = Depends(require_admin),
    error_type: Optional[str] = Query(None, max_length=100),
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Browse individual error records plus daily aggregate counts."""
    _require_db()
    try:
        errors = await db.admin_list_errors(limit=limit, offset=offset, error_type=error_type)
        stats = await db.get_error_stats(days=days)
        return {"errors": errors, "stats": stats}
    except Exception as e:
        logger.error(f"Error listing errors: {e}")
        raise HTTPException(status_code=500, detail="Failed to list errors")


@router.get("/purchases")
async def list_purchases(
    admin: dict = Depends(require_admin),
    status: Optional[str] = Query(None, pattern="^(pending|completed|failed|refunded)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List purchases across all users, optionally filtered by status."""
    _require_db()
    try:
        purchases = await db.admin_list_purchases(status=status, limit=limit, offset=offset)
        return {"purchases": purchases}
    except Exception as e:
        logger.error(f"Error listing purchases: {e}")
        raise HTTPException(status_code=500, detail="Failed to list purchases")


@router.get("/analytics")
async def get_analytics(
    admin: dict = Depends(require_admin),
    days: int = Query(7, ge=1, le=365),
):
    """Session, referrer, device, and TTS usage statistics.

    Exposes the aggregate functions that already existed in the database
    layer but previously had no API surface.
    """
    _require_db()
    try:
        return {
            "sessions": await db.get_session_stats(days=days),
            "referrers": await db.get_referrer_stats(days=days),
            "devices": await db.get_device_stats(days=days),
            "tts": await db.get_tts_stats(days=days),
        }
    except Exception as e:
        logger.error(f"Error building analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to load analytics")


@router.get("/costs")
async def get_costs(
    admin: dict = Depends(require_admin),
    days: int = Query(30, ge=1, le=365),
):
    """Estimated LLM spend and token volume per day."""
    _require_db()
    try:
        costs = await db.admin_get_llm_cost_stats(days=days)
        return {"costs": costs}
    except Exception as e:
        logger.error(f"Error building cost stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to load cost stats")


@router.get("/audit-log")
async def list_audit_log(
    admin: dict = Depends(require_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Browse the trail of privileged admin actions."""
    _require_db()
    try:
        entries = await db.admin_list_audit_log(limit=limit, offset=offset)
        return {"audit_log": entries}
    except Exception as e:
        logger.error(f"Error listing audit log: {e}")
        raise HTTPException(status_code=500, detail="Failed to list audit log")

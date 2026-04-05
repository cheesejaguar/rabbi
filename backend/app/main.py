"""FastAPI application for rebbe.dev -- a multi-agent Torah wisdom chatbot.

This module defines the main FastAPI application, including:

- **CORS middleware** for cross-origin browser requests.
- **Security headers middleware** (X-Frame-Options, HSTS, etc.).
- **Request size limiting middleware** to prevent DoS via oversized bodies.
- **Authentication middleware** protecting non-public routes via WorkOS sessions.
- **Rate limiting** via slowapi, keyed on authenticated user ID or client IP.
- **Multi-agent chat pipeline** that streams Torah responses as Server-Sent Events.
- **Guest access management** with cookie + IP-based chat tracking.
- **Credit system endpoints** for authenticated users.
- **Feedback and analytics endpoints** for message ratings and session tracking.
- **Text-to-speech endpoints** using ElevenLabs streaming API.
- **Static file serving** for the vanilla HTML/JS/CSS frontend.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import uuid
import json
import httpx
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os

logger = logging.getLogger(__name__)

from .config import get_settings
from .models import (
    ChatRequest,
    ChatResponse,
    DvarTorahResponse,
    GreetingResponse,
    HealthResponse,
    ProfileUpdate,
    ProfileResponse,
)
from .agents.denominations import VALID_DENOMINATIONS
from .agents import RabbiOrchestrator
from .auth import (
    router as auth_router,
    get_current_user,
    require_auth,
    get_guest_chats_used,
    create_guest_chat_cookie,
    GUEST_FREE_CHAT_LIMIT,
    LOGGED_IN_FREE_CREDITS,
)
from .security import (
    guest_security,
    input_validator,
    GUEST_RATE_LIMIT_PER_MINUTE,
)
from .conversations import router as conversations_router
from .payments import router as payments_router
from . import database as db
from .dvar_torah import get_or_generate_dvar_torah

# ---------------------------------------------------------------------------
# App Configuration & Middleware
# ---------------------------------------------------------------------------

settings = get_settings()


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


def get_rate_limit_key(request: Request) -> str:
    """Derive the rate-limit bucket key for the current request.

    Authenticated users are keyed by their unique user ID so that
    rate limits apply per-account. Unauthenticated (guest) users
    fall back to the client IP address.

    Args:
        request: The incoming FastAPI request object.

    Returns:
        A string key in the format ``"user:<id>"`` or ``"guest:<ip>"``.
    """
    # Check for authenticated user
    user = get_current_user(request)
    if user:
        return f"user:{user['id']}"
    # Fall back to IP address for guests
    return f"guest:{get_remote_address(request)}"


def get_guest_rate_limit_key(request: Request) -> str:
    """Derive a rate-limit key specifically for guest (unauthenticated) tracking.

    Always uses the client IP address regardless of authentication state.

    Args:
        request: The incoming FastAPI request object.

    Returns:
        A string key in the format ``"guest:<ip>"``.
    """
    return f"guest:{get_remote_address(request)}"


# Initialize rate limiter -- uses the per-user/IP key function above
limiter = Limiter(key_func=get_rate_limit_key)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return a 429 JSON response when the client exceeds its rate limit.

    Args:
        request: The incoming FastAPI request object.
        exc: The slowapi ``RateLimitExceeded`` exception instance.

    Returns:
        A ``JSONResponse`` with HTTP 429 status, a ``Retry-After`` header,
        and a JSON body containing the error detail.
    """
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please slow down.",
            "retry_after": exc.detail,
        },
        headers={"Retry-After": str(getattr(exc, 'retry_after', 60))},
    )


orchestrator = RabbiOrchestrator(
    api_key=settings.llm_api_key or None,
    base_url=settings.llm_base_url,
    model=settings.llm_model,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle.

    On startup, initializes the PostgreSQL schema (if a database URL is
    configured). On shutdown, gracefully closes the asyncpg connection pool.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the running application between startup and shutdown.
    """
    # Startup: Initialize database schema if configured
    if settings.db_url:
        try:
            await db.init_schema()
            logger.info("Database schema initialized")
        except Exception as e:
            logger.warning(f"Could not initialize database: {e}")
    # Pre-warm RAG index (nice-to-have; halachic agent also loads lazily)
    orchestrator.ensure_rag()
    yield
    # Shutdown: Close database pool
    await db.close_pool()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A progressive Modern Orthodox AI rebbe - guidance, not psak",
    lifespan=lifespan,
)

# Add rate limiter to app state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS middleware - origins configured via environment
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Cookie"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject browser security headers into every HTTP response.

    Headers applied:
        - ``X-Frame-Options: DENY`` -- prevents clickjacking via iframes.
        - ``X-Content-Type-Options: nosniff`` -- stops MIME-type sniffing.
        - ``X-XSS-Protection: 1; mode=block`` -- legacy XSS filter hint.
        - ``Referrer-Policy`` -- limits referrer leakage.
        - ``Permissions-Policy`` -- disables camera, mic, and geolocation.
        - ``Strict-Transport-Security`` -- HSTS, production only.
    """

    async def dispatch(self, request: Request, call_next):
        """Process request and attach security headers to the response.

        Args:
            request: The incoming HTTP request.
            call_next: Callable to forward the request to the next middleware
                or the actual route handler.

        Returns:
            The response with security headers appended.
        """
        response = await call_next(request)
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # XSS protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy - disable unnecessary features
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS - only in production (when cookies are secure)
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose ``Content-Length`` exceeds a safe threshold.

    This is a lightweight DoS mitigation layer. It checks the declared
    ``Content-Length`` header and returns HTTP 413 if the body would
    exceed ``MAX_BODY_SIZE`` (1 MB).
    """

    MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB limit

    async def dispatch(self, request: Request, call_next):
        """Validate request body size before forwarding to the handler.

        Args:
            request: The incoming HTTP request.
            call_next: Callable to forward the request downstream.

        Returns:
            HTTP 413 ``JSONResponse`` if body is too large, otherwise the
            downstream response.
        """
        # Check Content-Length header
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.MAX_BODY_SIZE:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
            except ValueError:
                pass  # Invalid Content-Length, let request proceed
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on non-public routes.

    Routes listed in ``PUBLIC_PATHS`` or matching ``PUBLIC_PREFIXES`` are
    exempt. All other requests must carry a valid session cookie. API
    routes receive HTTP 401; browser page requests are redirected to the
    logged-out landing page.
    """

    # Paths that don't require authentication (exact match)
    PUBLIC_PATHS = {
        "/auth/login",
        "/auth/callback",
        "/auth/check",
        "/api/health",
        "/api/analytics",  # Allow anonymous session tracking
        "/api/payments/webhook",  # Stripe webhook (verified by signature)
        "/api/guest/status",  # Guest chat status check
        "/api/chat/stream",  # Allow guest free chat (handled in endpoint)
        "/api/greeting",  # Allow guests to see greeting
        "/api/dvar-torah",  # Weekly d'var Torah (public, cached)
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    # Path prefixes that don't require authentication
    PUBLIC_PREFIXES = ("/static/", "/auth/")

    async def dispatch(self, request: Request, call_next):
        """Check authentication and either forward or reject the request.

        Args:
            request: The incoming HTTP request.
            call_next: Callable to forward the request downstream.

        Returns:
            The downstream response for authenticated or public requests,
            HTTP 401 JSON for unauthenticated API calls, or a 302 redirect
            for unauthenticated page requests.
        """
        path = request.url.path

        # Allow public paths (exact match against the set)
        if path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Allow public prefixes (startswith check)
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Check authentication for all other paths
        user = get_current_user(request)
        if not user:
            # For API requests, return 401 JSON
            if path.startswith("/api/"):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"}
                )
            # For page requests, redirect to logged-out page (not auto-login)
            return RedirectResponse(url="/auth/logged-out", status_code=302)

        return await call_next(request)


# Add auth middleware (outermost -- runs first on every request)
app.add_middleware(AuthMiddleware)

# Include sub-routers for auth, conversations, and payments
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(payments_router)


# ---------------------------------------------------------------------------
# Health & Utility Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Return service health status and version.

    Returns:
        HealthResponse: JSON with ``status`` and ``version`` fields.
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
    )


@app.get("/api/greeting", response_model=GreetingResponse)
@limiter.limit("30/minute")
async def get_greeting(request: Request):
    """Generate and return an initial greeting message.

    The greeting is produced by the rabbinic orchestrator and varies
    based on the time of day and Jewish calendar context.

    Args:
        request: The incoming HTTP request (used by the rate limiter).

    Returns:
        GreetingResponse: JSON with a ``greeting`` string.
    """
    greeting = await orchestrator.get_greeting()
    return GreetingResponse(greeting=greeting)


@app.get("/api/dvar-torah", response_model=DvarTorahResponse)
@limiter.limit("30/minute")
async def get_dvar_torah(request: Request):
    """Retrieve the weekly d'var Torah for the current parsha.

    Attempts to load a cached commentary or generate one on the fly.
    Returns an empty response with ``is_holiday_week=True`` if no regular
    parsha is read this week (e.g., during holiday weeks).

    Args:
        request: The incoming HTTP request (used by the rate limiter).

    Returns:
        DvarTorahResponse: JSON with parsha details and the commentary
        text, wrapped in a ``Cache-Control: public, max-age=3600`` header.
    """
    try:
        result = await get_or_generate_dvar_torah(orchestrator.client, orchestrator.model)
    except Exception as e:
        logger.error(f"D'var Torah error: {e}")
        result = None

    if result is None:
        return DvarTorahResponse(
            parsha_name="",
            parsha_name_hebrew="",
            hebrew_year=0,
            content="",
            is_holiday_week=True,
        )

    response = DvarTorahResponse(
        parsha_name=result["parsha_name"],
        parsha_name_hebrew=result["parsha_name_hebrew"],
        hebrew_year=result["hebrew_year"],
        content=result["content"],
        is_holiday_week=False,
    )

    return JSONResponse(
        content=response.model_dump(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ---------------------------------------------------------------------------
# Guest Management
# ---------------------------------------------------------------------------


@app.get("/api/guest/status")
@limiter.limit("60/minute")
async def get_guest_status(request: Request):
    """Report how many free guest chats remain for the current visitor.

    For authenticated users, returns the credit-based system info instead.
    For guests, the effective count is the *maximum* of the signed cookie
    count and the server-side IP tracker (guards against cookie clearing).

    Args:
        request: The incoming HTTP request.

    Returns:
        JSONResponse with fields: ``is_guest``, ``chats_used``,
        ``chats_remaining``, ``limit``, and optionally ``blocked`` /
        ``block_reason``.

    Raises:
        HTTP 403: If the guest IP has been blocked for abuse.
    """
    user = get_current_user(request)
    if user:
        # User is logged in - they have their credits system
        return JSONResponse(content={
            "is_guest": False,
            "chats_used": 0,
            "chats_remaining": LOGGED_IN_FREE_CREDITS,
            "limit": LOGGED_IN_FREE_CREDITS,
        })

    # Check if IP is blocked due to rate-limit violations
    is_blocked, block_reason = guest_security.is_ip_blocked(request)
    if is_blocked:
        return JSONResponse(
            status_code=403,
            content={
                "is_guest": True,
                "chats_used": GUEST_FREE_CHAT_LIMIT,
                "chats_remaining": 0,
                "limit": GUEST_FREE_CHAT_LIMIT,
                "blocked": True,
                "block_reason": block_reason,
            }
        )

    # Guest user - check both cookie and IP tracking
    cookie_count = get_guest_chats_used(request)
    effective_count = guest_security.get_effective_guest_count(request, cookie_count)
    chats_remaining = max(0, GUEST_FREE_CHAT_LIMIT - effective_count)

    return JSONResponse(content={
        "is_guest": True,
        "chats_used": effective_count,
        "chats_remaining": chats_remaining,
        "limit": GUEST_FREE_CHAT_LIMIT,
    })


# ---------------------------------------------------------------------------
# Credits & Profile
# ---------------------------------------------------------------------------


@app.get("/api/credits")
@limiter.limit("60/minute")
async def get_credits(request: Request):
    """Return the authenticated user's remaining chat credits.

    If no database is configured, assumes unlimited credits (development
    mode). Defaults to 3 credits on read failure as a safe fallback.

    Args:
        request: The incoming HTTP request.

    Returns:
        JSON dict with ``credits`` (int) and ``unlimited`` (bool).

    Raises:
        HTTPException: 401 if the user is not authenticated.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.db_url:
        # If no database, return unlimited credits
        return {"credits": -1, "unlimited": True}

    try:
        credits = await db.get_user_credits(user["id"])
        return {"credits": credits if credits is not None else 3, "unlimited": False}
    except Exception as e:
        logger.error(f"Error getting credits: {e}")
        return {"credits": 3, "unlimited": False}


@app.get("/api/profile", response_model=ProfileResponse)
@limiter.limit("60/minute")
async def get_profile(request: Request):
    """Retrieve the authenticated user's profile (denomination and bio).

    Args:
        request: The incoming HTTP request.

    Returns:
        ProfileResponse: JSON with ``denomination`` and ``bio`` fields.

    Raises:
        HTTPException: 401 if the user is not authenticated.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.db_url:
        # If no database, return defaults
        return ProfileResponse(denomination="just_jewish", bio="")

    try:
        profile = await db.get_user_profile(user["id"])
        if profile:
            return ProfileResponse(
                denomination=profile.get("denomination", "just_jewish"),
                bio=profile.get("bio", "")
            )
        return ProfileResponse(denomination="just_jewish", bio="")
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        return ProfileResponse(denomination="just_jewish", bio="")


@app.put("/api/profile", response_model=ProfileResponse)
@limiter.limit("30/minute")
async def update_profile(request: Request, profile_update: ProfileUpdate):
    """Update the authenticated user's denomination and/or bio.

    Validates the denomination against ``VALID_DENOMINATIONS`` before
    persisting. Returns the updated profile on success.

    Args:
        request: The incoming HTTP request.
        profile_update: Request body with optional ``denomination`` and
            ``bio`` fields.

    Returns:
        ProfileResponse: The updated profile.

    Raises:
        HTTPException: 400 for invalid denomination, 401 if not
            authenticated, 503 if database is not configured.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.db_url:
        raise HTTPException(status_code=503, detail="Database not configured")

    # Validate denomination if provided and non-empty
    if profile_update.denomination is not None and profile_update.denomination != "":
        if profile_update.denomination not in VALID_DENOMINATIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid denomination. Must be one of: {', '.join(VALID_DENOMINATIONS)}"
            )

    try:
        success = await db.update_user_profile(
            user["id"],
            denomination=profile_update.denomination,
            bio=profile_update.bio
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update profile")

        # Return updated profile
        profile = await db.get_user_profile(user["id"])
        return ProfileResponse(
            denomination=profile.get("denomination", "just_jewish"),
            bio=profile.get("bio", "")
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")


# ---------------------------------------------------------------------------
# Feedback & Analytics
# ---------------------------------------------------------------------------


@app.post("/api/feedback")
@limiter.limit("30/minute")
async def submit_feedback(request: Request):
    """Submit or update thumbs-up/thumbs-down feedback for a message.

    Uses an upsert so that re-submitting for the same message replaces
    the previous rating.

    Args:
        request: The incoming HTTP request. JSON body must contain
            ``message_id`` (str) and ``feedback_type``
            (``"thumbs_up"`` | ``"thumbs_down"``).

    Returns:
        JSON dict with ``success`` (bool) and ``feedback`` (dict).

    Raises:
        HTTPException: 400 for invalid input, 401 if not authenticated,
            503 if no database.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.db_url:
        raise HTTPException(status_code=503, detail="Database not configured")

    body = await request.json()
    message_id = body.get("message_id")
    feedback_type = body.get("feedback_type")

    if not message_id or feedback_type not in ("thumbs_up", "thumbs_down"):
        raise HTTPException(status_code=400, detail="Invalid request")

    try:
        result = await db.upsert_feedback(message_id, user["id"], feedback_type)
        return {"success": True, "feedback": result}
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")


@app.delete("/api/feedback/{message_id}")
@limiter.limit("30/minute")
async def remove_feedback(request: Request, message_id: str):
    """Remove the authenticated user's feedback for a specific message.

    Args:
        request: The incoming HTTP request.
        message_id: UUID of the message whose feedback should be removed.

    Returns:
        JSON dict with ``success`` (bool).

    Raises:
        HTTPException: 401 if not authenticated, 503 if no database.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.db_url:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        deleted = await db.delete_feedback(message_id, user["id"])
        return {"success": deleted}
    except Exception as e:
        logger.error(f"Error deleting feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete feedback")


@app.post("/api/tts-event")
@limiter.limit("60/minute")
async def log_tts_event(request: Request):
    """Record a text-to-speech lifecycle event for analytics.

    Valid event types: ``start``, ``stop``, ``complete``, ``error``.

    Args:
        request: The incoming HTTP request. JSON body should contain
            ``event_type`` (str, required), and optionally ``message_id``,
            ``text_length``, ``duration_ms``, ``error_message``.

    Returns:
        JSON dict with ``success`` (bool) and ``event_id`` (str).

    Raises:
        HTTPException: 400 for invalid event_type, 401 if not authenticated.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.db_url:
        return {"success": False, "message": "Database not configured"}

    body = await request.json()
    event_type = body.get("event_type")
    message_id = body.get("message_id")
    text_length = body.get("text_length")
    duration_ms = body.get("duration_ms")
    error_message = body.get("error_message")

    if event_type not in ("start", "stop", "complete", "error"):
        raise HTTPException(status_code=400, detail="Invalid event_type")

    try:
        result = await db.log_tts_event(
            user_id=user["id"],
            event_type=event_type,
            message_id=message_id,
            text_length=text_length,
            duration_ms=duration_ms,
            error_message=error_message
        )
        return {"success": True, "event_id": result.get("id")}
    except Exception as e:
        logger.error(f"Error logging TTS event: {e}")
        return {"success": False}


@app.post("/api/analytics")
@limiter.limit("120/minute")
async def log_analytics_event(request: Request):
    """Record a client-side analytics event (page view, session start, etc.).

    This endpoint is publicly accessible (no auth required) so that
    anonymous session tracking works for all visitors.

    Args:
        request: The incoming HTTP request. JSON body must contain
            ``session_id`` (str) and ``event_type`` (str). Optional:
            ``event_data`` (dict), ``page_path``, ``referrer``.

    Returns:
        JSON dict with ``success`` (bool) and ``event_id`` (str).

    Raises:
        HTTPException: 400 if ``session_id`` or ``event_type`` is missing.
    """
    user = get_current_user(request)

    if not settings.db_url:
        return {"success": False, "message": "Database not configured"}

    body = await request.json()
    session_id = body.get("session_id")
    event_type = body.get("event_type")
    event_data = body.get("event_data", {})
    page_path = body.get("page_path")
    referrer = body.get("referrer")

    if not session_id or not event_type:
        raise HTTPException(status_code=400, detail="session_id and event_type required")

    # Get user agent from headers for device-type analytics
    user_agent = request.headers.get("user-agent", "")

    try:
        result = await db.log_analytics_event(
            session_id=session_id,
            event_type=event_type,
            user_id=user["id"] if user else None,
            event_data=event_data,
            page_path=page_path,
            referrer=referrer,
            user_agent=user_agent
        )
        return {"success": True, "event_id": result.get("id")}
    except Exception as e:
        logger.error(f"Error logging analytics event: {e}")
        return {"success": False}


# ---------------------------------------------------------------------------
# TTS Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/speak")
@limiter.limit("10/minute")
async def text_to_speech(request: Request):
    """Stream text-to-speech audio using the ElevenLabs API.

    Proxies the request to ElevenLabs and returns raw PCM audio at
    24 kHz / 16-bit as a streaming response. The frontend plays this
    directly via the Web Audio API.

    Args:
        request: The incoming HTTP request. JSON body must include
            ``text`` (str).

    Returns:
        StreamingResponse: Raw PCM audio stream with headers
        ``X-Sample-Rate: 24000`` and ``X-Bit-Depth: 16``.

    Raises:
        HTTPException: 400 if text is empty, 401 if not authenticated,
            503 if ElevenLabs is not configured.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.elevenlabs_api_key:
        raise HTTPException(status_code=503, detail="ElevenLabs not configured")

    body = await request.json()
    text = body.get("text", "")

    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    async def stream_audio():
        """Yield raw PCM audio chunks from ElevenLabs streaming endpoint."""
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}/stream",
                params={"output_format": "pcm_24000"},
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "text": text,
                    "model_id": "eleven_v3"
                },
                timeout=120.0
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    logger.error(f"ElevenLabs API error: {response.status_code}")
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        stream_audio(),
        media_type="audio/pcm",
        headers={
            "Content-Type": "audio/pcm",
            "X-Sample-Rate": "24000",
            "X-Bit-Depth": "16",
            "Cache-Control": "no-cache",
        }
    )


# ---------------------------------------------------------------------------
# Chat Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(f"{settings.rate_limit_chat_per_minute}/minute")
async def chat(request: Request, chat_request: ChatRequest):
    """Process a chat message through the non-streaming rebbe.dev pipeline.

    The message flows through four specialized agents:

    1. **Pastoral Context Agent** -- determines *how* to respond.
    2. **Halachic Reasoning Agent** -- provides the halachic landscape.
    3. **Moral-Ethical Agent** -- ensures dignity and prevents harm.
    4. **Meta-Rabbinic Voice Agent** -- crafts the final response.

    Args:
        request: The incoming HTTP request.
        chat_request: Validated request body with ``message``,
            ``conversation_history``, and optional ``session_id`` /
            ``conversation_id``.

    Returns:
        ChatResponse: The rabbi's response, referral flag, session/
        conversation IDs, and pipeline metadata.

    Raises:
        HTTPException: 400 for invalid input, 403 if guest IP is blocked,
            429 if rate-limited, 500 on pipeline errors.
    """
    user = get_current_user(request)

    # Security checks for unauthenticated users
    if not user:
        # Check if IP is blocked
        is_blocked, block_reason = guest_security.is_ip_blocked(request)
        if is_blocked:
            raise HTTPException(status_code=403, detail=block_reason)

        # Check guest rate limit
        rate_ok, rate_error = guest_security.check_rate_limit(request)
        if not rate_ok:
            raise HTTPException(status_code=429, detail=rate_error)

    # Input validation
    is_valid, validation_error = input_validator.validate_message(chat_request.message)
    if not is_valid:
        raise HTTPException(status_code=400, detail=validation_error)

    # Sanitize the message
    sanitized_message = input_validator.sanitize_message(chat_request.message)

    try:
        conversation_history = [
            {"role": msg.role, "content": msg.content}
            for msg in chat_request.conversation_history
        ]

        # Get user profile for personalized responses
        user_denomination = None
        user_bio = None
        if user and settings.db_url:
            try:
                profile = await db.get_user_profile(user["id"])
                if profile:
                    user_denomination = profile.get("denomination")
                    user_bio = profile.get("bio")
            except Exception as e:
                logger.warning(f"Could not get user profile: {e}")

        result = await orchestrator.process_message(
            user_message=sanitized_message,
            conversation_history=conversation_history,
            user_denomination=user_denomination,
            user_bio=user_bio,
        )

        session_id = chat_request.session_id or str(uuid.uuid4())

        return ChatResponse(
            response=result["response"],
            requires_human_referral=result["requires_human_referral"],
            session_id=session_id,
            metadata=result["metadata"],
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred processing your message. Please try again."
        )


@app.post("/api/chat/stream")
@limiter.limit(f"{settings.rate_limit_chat_per_minute}/minute")
async def chat_stream(request: Request, chat_request: ChatRequest):
    """Process a chat message and stream the response as Server-Sent Events.

    The message flows through the same four-agent pipeline as ``/api/chat``,
    but the final Voice Agent streams tokens incrementally.

    SSE event types emitted by the generator:

    - **session** -- ``{session_id, conversation_id}`` sent first.
    - **token** -- ``{data: "<text>"}`` for each streaming text chunk.
    - **metrics** -- ``{data: {…}}`` with pipeline timing/metadata.
    - **message_saved** -- ``{message_id}`` after the assistant message
      is persisted to the database.
    - **done** -- ``{}`` signals the stream is complete.
    - **error** -- ``{message, detail?}`` on failure.

    For guest (unauthenticated) users the endpoint enforces:

    - IP block-list checks.
    - Per-minute rate limiting (stricter than authenticated).
    - A per-IP daily free-chat quota tracked by both a signed cookie
      and a server-side IP counter (guards against cookie clearing).

    Args:
        request: The incoming HTTP request.
        chat_request: Validated request body (same schema as ``/api/chat``).

    Returns:
        StreamingResponse: ``text/event-stream`` with SSE-formatted JSON
        events. A ``guest_chats_used`` cookie is set for guest visitors.
    """
    # Get current user for database operations
    user = get_current_user(request)

    # Security checks for unauthenticated users
    if not user:
        # Check if IP is blocked
        is_blocked, block_reason = guest_security.is_ip_blocked(request)
        if is_blocked:
            logger.warning(f"Blocked request from IP: {block_reason}")
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'message': 'access_restricted', 'detail': block_reason})}\n\n"]),
                media_type="text/event-stream",
            )

        # Check guest rate limit (stricter than authenticated users)
        rate_ok, rate_error = guest_security.check_rate_limit(request)
        if not rate_ok:
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'message': 'rate_limited', 'detail': rate_error})}\n\n"]),
                media_type="text/event-stream",
            )

    # Input validation
    is_valid, validation_error = input_validator.validate_message(chat_request.message)
    if not is_valid:
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'message': 'invalid_input', 'detail': validation_error})}\n\n"]),
            media_type="text/event-stream",
        )

    # Sanitize the message
    sanitized_message = input_validator.sanitize_message(chat_request.message)

    conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in chat_request.conversation_history
    ]

    session_id = chat_request.session_id or str(uuid.uuid4())
    conversation_id = chat_request.conversation_id

    # Track if this is a guest chat that needs cookie update
    is_guest_chat = False
    new_guest_chats_used = 0

    # Handle guest users (not logged in)
    if not user:
        cookie_count = get_guest_chats_used(request)

        # Check IP-based tracking (catches cookie clearing)
        ip_allowed, ip_error = guest_security.check_guest_chat_allowed(request, cookie_count)
        if not ip_allowed:
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'message': 'guest_limit_reached', 'detail': ip_error})}\n\n"]),
                media_type="text/event-stream",
            )

        # Use effective count (max of cookie and IP tracking)
        effective_count = guest_security.get_effective_guest_count(request, cookie_count)

        if effective_count >= GUEST_FREE_CHAT_LIMIT:
            # Guest has used their free chat - prompt to login
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'message': 'guest_limit_reached', 'detail': 'Sign in for 3 more free chats'})}\n\n"]),
                media_type="text/event-stream",
            )

        # Guest can chat - mark for cookie update after response
        is_guest_chat = True
        new_guest_chats_used = effective_count + 1

    # Get user profile for personalized responses
    user_denomination = None
    user_bio = None
    if user and settings.db_url:
        try:
            profile = await db.get_user_profile(user["id"])
            if profile:
                user_denomination = profile.get("denomination")
                user_bio = profile.get("bio")
        except Exception as e:
            logger.warning(f"Could not get user profile: {e}")

    # Check and consume credit before processing (only for logged-in users)
    if user and settings.db_url:
        try:
            has_credit = await db.consume_credit(user["id"])
            if not has_credit:
                return StreamingResponse(
                    iter([f"data: {json.dumps({'type': 'error', 'message': 'No credits remaining. Please contact support.'})}\n\n"]),
                    media_type="text/event-stream",
                )
        except Exception as e:
            logger.warning(f"Could not check credits: {e}")

    # Save user message to database if conversation_id provided
    if conversation_id and user and settings.db_url:
        try:
            await db.add_message(conversation_id, "user", sanitized_message)
        except Exception as e:
            logger.warning(f"Could not save user message: {e}")

    async def event_generator():
        """Yield SSE-formatted JSON events for the streaming chat response.

        Accumulates the full response text and pipeline metrics so they
        can be persisted to the database after streaming completes.

        Yields:
            Strings in SSE ``data: <json>\\n\\n`` format.
        """
        full_response = ""
        metrics_data = None
        try:
            # Emit session context so the client can associate this stream
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'conversation_id': conversation_id})}\n\n"

            async for event in orchestrator.process_message_stream(
                user_message=sanitized_message,
                conversation_history=conversation_history,
                user_denomination=user_denomination,
                user_bio=user_bio,
            ):
                yield f"data: {json.dumps(event)}\n\n"

                # Accumulate streaming tokens into full_response for DB persistence
                if event.get("type") == "token":
                    full_response += event.get("data", "")
                # Capture pipeline metrics (timing, token counts, etc.)
                elif event.get("type") == "metrics":
                    metrics_data = event.get("data", {})

            # Save assistant response to database with metrics
            if conversation_id and user and settings.db_url and full_response:
                try:
                    # Include metrics in message metadata
                    metadata = metrics_data if metrics_data else {}
                    message = await db.add_message(conversation_id, "assistant", full_response, metadata)
                    # Emit message_id so frontend can track feedback
                    if message and message.get("id"):
                        yield f"data: {json.dumps({'type': 'message_saved', 'message_id': message['id']})}\n\n"
                    # Update conversation title if not set
                    conv = await db.get_conversation(conversation_id, user["id"])
                    if conv and not conv.get("title"):
                        title = await db.generate_conversation_title(conversation_id)
                        if title:
                            await db.update_conversation(conversation_id, user["id"], title)
                except Exception as e:
                    logger.warning(f"Could not save assistant message: {e}")

            # Send done event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            # Log error to database
            if settings.db_url:
                try:
                    await db.log_error(
                        error_type="llm_error",
                        error_message=str(e),
                        user_id=user["id"] if user else None,
                        conversation_id=conversation_id,
                        request_context={"message": sanitized_message[:500]}
                    )
                except Exception:
                    pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    response = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

    # Set guest chat cookie and record to server-side IP tracker
    if is_guest_chat:
        guest_cookie = create_guest_chat_cookie(new_guest_chats_used)
        response.set_cookie(
            key="guest_chats_used",
            value=guest_cookie,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=86400 * 30,  # 30-day expiry
            path="/",
        )
        # Also record in IP tracker (guards against cookie clearing)
        guest_security.record_guest_chat(request)

    return response


# ---------------------------------------------------------------------------
# Static File Serving
# ---------------------------------------------------------------------------

frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    # Mount the frontend directory at /static for CSS, JS, and asset files
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve the single-page frontend application (index.html).

        Returns:
            FileResponse: The main ``index.html`` file from the frontend
            directory.
        """
        return FileResponse(os.path.join(frontend_path, "index.html"))

"""FastAPI application for rebbe.dev."""

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
from .conversations import router as conversations_router
from .payments import router as payments_router
from . import database as db

settings = get_settings()


def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key - use user ID if authenticated, otherwise IP address."""
    # Check for authenticated user
    user = get_current_user(request)
    if user:
        return f"user:{user['id']}"
    # Fall back to IP address
    return get_remote_address(request)


# Initialize rate limiter
limiter = Limiter(key_func=get_rate_limit_key)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please slow down.",
            "retry_after": exc.detail,
        },
        headers={"Retry-After": str(getattr(exc, 'retry_after', 60))},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    # Startup: Initialize database schema if configured
    if settings.db_url:
        try:
            await db.init_schema()
            logger.info("Database schema initialized")
        except Exception as e:
            logger.warning(f"Could not initialize database: {e}")
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
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
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
    """Limit request body size to prevent DoS attacks."""

    MAX_BODY_SIZE = 1 * 1024 * 1024  # 1MB limit

    async def dispatch(self, request: Request, call_next):
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
    """Middleware to require authentication for protected routes."""

    # Paths that don't require authentication
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
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    # Path prefixes that don't require authentication
    PUBLIC_PREFIXES = ("/static/", "/auth/")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths
        if path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Allow public prefixes
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Check authentication for all other paths
        user = get_current_user(request)
        if not user:
            # For API requests, return 401
            if path.startswith("/api/"):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"}
                )
            # For page requests, redirect to logged-out page (not auto-login)
            return RedirectResponse(url="/auth/logged-out", status_code=302)

        return await call_next(request)


# Add auth middleware
app.add_middleware(AuthMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(payments_router)

orchestrator = RabbiOrchestrator(
    api_key=settings.llm_api_key or None,
    base_url=settings.llm_base_url,
    model=settings.llm_model,
)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
    )


@app.get("/api/greeting", response_model=GreetingResponse)
@limiter.limit("30/minute")
async def get_greeting(request: Request):
    """Get initial greeting message."""
    greeting = await orchestrator.get_greeting()
    return GreetingResponse(greeting=greeting)


@app.get("/api/guest/status")
@limiter.limit("60/minute")
async def get_guest_status(request: Request):
    """Get guest chat status - how many free chats remain."""
    user = get_current_user(request)
    if user:
        # User is logged in - they have their credits system
        return JSONResponse(content={
            "is_guest": False,
            "chats_used": 0,
            "chats_remaining": LOGGED_IN_FREE_CREDITS,
            "limit": LOGGED_IN_FREE_CREDITS,
        })

    # Guest user - check cookie
    chats_used = get_guest_chats_used(request)
    chats_remaining = max(0, GUEST_FREE_CHAT_LIMIT - chats_used)

    return JSONResponse(content={
        "is_guest": True,
        "chats_used": chats_used,
        "chats_remaining": chats_remaining,
        "limit": GUEST_FREE_CHAT_LIMIT,
    })


@app.get("/api/credits")
@limiter.limit("60/minute")
async def get_credits(request: Request):
    """Get the current user's remaining credits."""
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
    """Get the current user's profile (denomination and bio)."""
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
    """Update the current user's profile (denomination and/or bio)."""
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


@app.post("/api/feedback")
@limiter.limit("30/minute")
async def submit_feedback(request: Request):
    """Submit thumbs up/down feedback for a message."""
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
    """Remove feedback for a message."""
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
    """Log a TTS (text-to-speech) usage event."""
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
    """Log an analytics event (page view, session, etc.)."""
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

    # Get user agent from headers
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


@app.post("/api/speak")
@limiter.limit("10/minute")
async def text_to_speech(request: Request):
    """Convert text to speech using ElevenLabs streaming API with PCM output."""
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
        """Stream PCM audio chunks from ElevenLabs."""
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


@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(f"{settings.rate_limit_chat_per_minute}/minute")
async def chat(request: Request, chat_request: ChatRequest):
    """
    Process a chat message through the rebbe.dev pipeline.

    The message flows through four specialized agents:
    1. Pastoral Context Agent - Determines HOW to respond
    2. Halachic Reasoning Agent - Provides halachic landscape
    3. Moral-Ethical Agent - Ensures dignity and prevents harm
    4. Meta-Rabbinic Voice Agent - Crafts the final response
    """
    try:
        conversation_history = [
            {"role": msg.role, "content": msg.content}
            for msg in chat_request.conversation_history
        ]

        # Get user profile for personalized responses
        user = get_current_user(request)
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
            user_message=chat_request.message,
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
    """
    Process a chat message with streaming response using Server-Sent Events.

    The message flows through four specialized agents:
    1. Pastoral Context Agent - Determines HOW to respond
    2. Halachic Reasoning Agent - Provides halachic landscape
    3. Moral-Ethical Agent - Ensures dignity and prevents harm
    4. Meta-Rabbinic Voice Agent - Streams the final response
    """
    conversation_history = [
        {"role": msg.role, "content": msg.content}
        for msg in chat_request.conversation_history
    ]

    session_id = chat_request.session_id or str(uuid.uuid4())
    conversation_id = chat_request.conversation_id

    # Get current user for database operations
    user = get_current_user(request)

    # Track if this is a guest chat that needs cookie update
    is_guest_chat = False
    new_guest_chats_used = 0

    # Handle guest users (not logged in)
    if not user:
        chats_used = get_guest_chats_used(request)
        if chats_used >= GUEST_FREE_CHAT_LIMIT:
            # Guest has used their free chat - prompt to login
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'message': 'guest_limit_reached', 'detail': 'Sign in for 3 more free chats'})}\n\n"]),
                media_type="text/event-stream",
            )
        # Guest can chat - mark for cookie update after response
        is_guest_chat = True
        new_guest_chats_used = chats_used + 1

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
            await db.add_message(conversation_id, "user", chat_request.message)
        except Exception as e:
            logger.warning(f"Could not save user message: {e}")

    async def event_generator():
        full_response = ""
        metrics_data = None
        try:
            # Send session_id and conversation_id first
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'conversation_id': conversation_id})}\n\n"

            async for event in orchestrator.process_message_stream(
                user_message=chat_request.message,
                conversation_history=conversation_history,
                user_denomination=user_denomination,
                user_bio=user_bio,
            ):
                yield f"data: {json.dumps(event)}\n\n"

                # Accumulate response for database
                if event.get("type") == "token":
                    full_response += event.get("data", "")
                # Capture metrics
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
                        request_context={"message": chat_request.message[:500]}
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

    # Set guest chat cookie to track usage
    if is_guest_chat:
        guest_cookie = create_guest_chat_cookie(new_guest_chats_used)
        response.set_cookie(
            key="guest_chats_used",
            value=guest_cookie,
            httponly=True,
            secure=settings.is_production,
            samesite="lax",
            max_age=86400 * 30,  # 30 days
            path="/",
        )

    return response


frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve the frontend application."""
        return FileResponse(os.path.join(frontend_path, "index.html"))

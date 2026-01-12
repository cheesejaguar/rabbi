"""FastAPI application for rebbe.dev."""

import uuid
import json
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
import os

from .config import get_settings
from .models import (
    ChatRequest,
    ChatResponse,
    GreetingResponse,
    HealthResponse,
)
from .agents import RabbiOrchestrator
from .auth import router as auth_router, get_current_user, require_auth
from .conversations import router as conversations_router
from . import database as db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    # Startup: Initialize database schema if configured
    if settings.db_url:
        try:
            await db.init_schema()
            print("Database schema initialized")
        except Exception as e:
            print(f"Warning: Could not initialize database: {e}")
    yield
    # Shutdown: Close database pool
    await db.close_pool()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A progressive Modern Orthodox AI rebbe - guidance, not psak",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to require authentication for protected routes."""

    # Paths that don't require authentication
    PUBLIC_PATHS = {
        "/auth/login",
        "/auth/callback",
        "/auth/check",
        "/api/health",
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
async def get_greeting():
    """Get initial greeting message."""
    greeting = await orchestrator.get_greeting()
    return GreetingResponse(greeting=greeting)


@app.get("/api/credits")
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
        print(f"Error getting credits: {e}")
        return {"credits": 3, "unlimited": False}


@app.post("/api/feedback")
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
        print(f"Error saving feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")


@app.delete("/api/feedback/{message_id}")
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
        print(f"Error deleting feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete feedback")


@app.post("/api/speak")
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
                    print(f"ElevenLabs API error: {response.status_code} - {error_text}")
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
async def chat(request: ChatRequest):
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
            for msg in request.conversation_history
        ]

        result = await orchestrator.process_message(
            user_message=request.message,
            conversation_history=conversation_history,
        )

        session_id = request.session_id or str(uuid.uuid4())

        return ChatResponse(
            response=result["response"],
            requires_human_referral=result["requires_human_referral"],
            session_id=session_id,
            metadata=result["metadata"],
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred processing your message. Please try again. Error: {str(e)}"
        )


@app.post("/api/chat/stream")
async def chat_stream(chat_request: ChatRequest, request: Request):
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

    # Check and consume credit before processing
    if user and settings.db_url:
        try:
            has_credit = await db.consume_credit(user["id"])
            if not has_credit:
                return StreamingResponse(
                    iter([f"data: {json.dumps({'type': 'error', 'message': 'No credits remaining. Please contact support.'})}\n\n"]),
                    media_type="text/event-stream",
                )
        except Exception as e:
            print(f"Warning: Could not check credits: {e}")

    # Save user message to database if conversation_id provided
    if conversation_id and user and settings.db_url:
        try:
            await db.add_message(conversation_id, "user", chat_request.message)
        except Exception as e:
            print(f"Warning: Could not save user message: {e}")

    async def event_generator():
        full_response = ""
        try:
            # Send session_id and conversation_id first
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'conversation_id': conversation_id})}\n\n"

            async for event in orchestrator.process_message_stream(
                user_message=chat_request.message,
                conversation_history=conversation_history,
            ):
                yield f"data: {json.dumps(event)}\n\n"

                # Accumulate response for database
                if event.get("type") == "token":
                    full_response += event.get("data", "")

            # Save assistant response to database
            if conversation_id and user and settings.db_url and full_response:
                try:
                    message = await db.add_message(conversation_id, "assistant", full_response)
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
                    print(f"Warning: Could not save assistant message: {e}")

            # Send done event
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve the frontend application."""
        return FileResponse(os.path.join(frontend_path, "index.html"))

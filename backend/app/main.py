"""FastAPI application for rebbe.dev."""

import uuid
import json
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
                    await db.add_message(conversation_id, "assistant", full_response)
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

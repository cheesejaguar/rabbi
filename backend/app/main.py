"""FastAPI application for AI Rabbi."""

import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .config import get_settings
from .models import (
    ChatRequest,
    ChatResponse,
    GreetingResponse,
    HealthResponse,
)
from .agents import RabbiOrchestrator

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A progressive Modern Orthodox AI Rabbi - guidance, not psak",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = RabbiOrchestrator(
    api_key=settings.anthropic_api_key or None,
    model=settings.claude_model,
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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat message through the AI Rabbi pipeline.

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


frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve the frontend application."""
        return FileResponse(os.path.join(frontend_path, "index.html"))

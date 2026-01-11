"""Conversations API router."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from .auth import get_current_user
from . import database as db

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    """Request body for creating a conversation."""
    title: Optional[str] = None


class ConversationUpdate(BaseModel):
    """Request body for updating a conversation."""
    title: str


class MessageCreate(BaseModel):
    """Request body for adding a message."""
    role: str
    content: str
    metadata: Optional[dict] = None


@router.get("")
async def list_conversations(request: Request, limit: int = 50, offset: int = 0):
    """List all conversations for the current user."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        conversations = await db.list_conversations(user["id"], limit, offset)
        return {"conversations": conversations}
    except Exception as e:
        # If database not configured, return empty list
        if "Database URL not configured" in str(e):
            return {"conversations": [], "warning": "Database not configured"}
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_conversation(request: Request, body: ConversationCreate):
    """Create a new conversation."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Ensure user exists in database
        await db.upsert_user(
            user_id=user["id"],
            email=user.get("email", ""),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
        )

        conversation = await db.create_conversation(user["id"], body.title)
        return conversation
    except Exception as e:
        if "Database URL not configured" in str(e):
            raise HTTPException(status_code=503, detail="Database not configured")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{conversation_id}")
async def get_conversation(request: Request, conversation_id: str):
    """Get a conversation with its messages."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        conversation = await db.get_conversation(conversation_id, user["id"])
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = await db.get_messages(conversation_id)
        return {
            **conversation,
            "messages": messages,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{conversation_id}")
async def update_conversation(request: Request, conversation_id: str, body: ConversationUpdate):
    """Update a conversation's title."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        conversation = await db.update_conversation(conversation_id, user["id"], body.title)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str):
    """Delete a conversation."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        deleted = await db.delete_conversation(conversation_id, user["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{conversation_id}/messages")
async def add_message(request: Request, conversation_id: str, body: MessageCreate):
    """Add a message to a conversation."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Verify user owns the conversation
        conversation = await db.get_conversation(conversation_id, user["id"])
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        message = await db.add_message(conversation_id, body.role, body.content, body.metadata)

        # Auto-generate title if this is the first user message and no title set
        if body.role == "user" and not conversation.get("title"):
            title = await db.generate_conversation_title(conversation_id)
            if title:
                await db.update_conversation(conversation_id, user["id"], title)

        return message
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{conversation_id}/messages")
async def get_messages(request: Request, conversation_id: str, limit: int = 100):
    """Get messages for a conversation."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        # Verify user owns the conversation
        conversation = await db.get_conversation(conversation_id, user["id"])
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = await db.get_messages(conversation_id, limit)
        return {"messages": messages}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

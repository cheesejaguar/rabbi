"""REST API router for conversation CRUD operations.

All endpoints in this module require authentication via
``get_current_user()``. Users can only access their own conversations --
every database query filters by the authenticated user's ``user_id``,
ensuring strict tenant isolation.

Permission model:
    * **User isolation**: All ``db.*`` calls include the requesting user's
      ID, so a user can never read, update, or delete another user's
      conversations or messages.
    * **Ownership verification**: For sub-resource operations (e.g., adding
      a message), the conversation is first fetched with the user's ID to
      confirm ownership before proceeding.
"""

import logging
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from typing import Optional, Literal

from .auth import get_current_user
from . import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    """Request body for creating a conversation.

    Attributes:
        title: Optional human-readable title. If omitted, a title will
            be auto-generated from the first user message.
    """
    title: Optional[str] = Field(None, max_length=200)


class ConversationUpdate(BaseModel):
    """Request body for updating a conversation.

    Attributes:
        title: The new conversation title (required, 1-200 characters).
    """
    title: str = Field(..., min_length=1, max_length=200)


class MessageCreate(BaseModel):
    """Request body for adding a message to a conversation.

    Attributes:
        role: The message sender role -- ``"user"`` or ``"assistant"``.
        content: The message text content (1-50 000 characters).
        metadata: Optional dictionary of additional data to store with
            the message (e.g., token usage, agent pipeline context).
    """
    role: Literal["user", "assistant"] = Field(..., description="Message role")
    content: str = Field(..., min_length=1, max_length=50000)
    metadata: Optional[dict] = None


@router.get("")
async def list_conversations(
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Max conversations to return"),
    offset: int = Query(0, ge=0, description="Number of conversations to skip")
):
    """List all conversations for the authenticated user.

    Results are paginated via ``limit`` and ``offset`` query parameters.
    Only conversations belonging to the current user are returned.

    Args:
        request: The incoming FastAPI ``Request`` object.
        limit: Maximum number of conversations to return (1-100,
            default 50).
        offset: Number of conversations to skip for pagination
            (default 0).

    Returns:
        A JSON object with a ``conversations`` list. If the database is
        not configured, returns an empty list with a ``warning`` field.

    Raises:
        HTTPException: 401 if not authenticated, 500 on database errors.
    """
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
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to list conversations")


@router.post("")
async def create_conversation(request: Request, body: ConversationCreate):
    """Create a new conversation for the authenticated user.

    Ensures the user record exists in the database (via upsert) before
    creating the conversation.

    Args:
        request: The incoming FastAPI ``Request`` object.
        body: The request body with an optional ``title``.

    Returns:
        A JSON object representing the newly created conversation
        (including its generated ``id`` and timestamps).

    Raises:
        HTTPException: 401 if not authenticated, 503 if the database
            is not configured, 500 on database errors.
    """
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
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail="Failed to create conversation")


@router.get("/{conversation_id}")
async def get_conversation(request: Request, conversation_id: str):
    """Retrieve a conversation and all its messages.

    The conversation is fetched with the user's ID to enforce ownership.

    Args:
        request: The incoming FastAPI ``Request`` object.
        conversation_id: The UUID of the conversation to retrieve.

    Returns:
        A JSON object with the conversation metadata and a nested
        ``messages`` list.

    Raises:
        HTTPException: 401 if not authenticated, 404 if the
            conversation does not exist or belongs to another user,
            500 on database errors.
    """
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
        logger.error(f"Error getting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get conversation")


@router.patch("/{conversation_id}")
async def update_conversation(request: Request, conversation_id: str, body: ConversationUpdate):
    """Update a conversation's title.

    Only the owning user can update their conversation.

    Args:
        request: The incoming FastAPI ``Request`` object.
        conversation_id: The UUID of the conversation to update.
        body: The request body containing the new ``title``.

    Returns:
        A JSON object representing the updated conversation.

    Raises:
        HTTPException: 401 if not authenticated, 404 if the
            conversation does not exist or belongs to another user,
            500 on database errors.
    """
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
        logger.error(f"Error updating conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update conversation")


@router.delete("/{conversation_id}")
async def delete_conversation(request: Request, conversation_id: str):
    """Delete a conversation and all its messages.

    Only the owning user can delete their conversation.

    Args:
        request: The incoming FastAPI ``Request`` object.
        conversation_id: The UUID of the conversation to delete.

    Returns:
        ``{"deleted": true}`` on success.

    Raises:
        HTTPException: 401 if not authenticated, 404 if the
            conversation does not exist or belongs to another user,
            500 on database errors.
    """
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
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete conversation")


@router.post("/{conversation_id}/messages")
async def add_message(request: Request, conversation_id: str, body: MessageCreate):
    """Add a message to an existing conversation.

    Verifies conversation ownership before inserting. If this is the
    first user message and the conversation has no title, a title is
    auto-generated from the message content.

    Args:
        request: The incoming FastAPI ``Request`` object.
        conversation_id: The UUID of the conversation to add a message to.
        body: The request body containing ``role``, ``content``, and
            optional ``metadata``.

    Returns:
        A JSON object representing the newly created message (including
        its ``id`` and ``created_at`` timestamp).

    Raises:
        HTTPException: 401 if not authenticated, 404 if the
            conversation does not exist or belongs to another user,
            500 on database errors.
    """
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
        logger.error(f"Error adding message to conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add message")


@router.get("/{conversation_id}/messages")
async def get_messages(
    request: Request,
    conversation_id: str,
    limit: int = Query(100, ge=1, le=500, description="Max messages to return")
):
    """Retrieve messages for a conversation.

    Verifies conversation ownership before returning messages.

    Args:
        request: The incoming FastAPI ``Request`` object.
        conversation_id: The UUID of the conversation.
        limit: Maximum number of messages to return (1-500, default 100).

    Returns:
        A JSON object with a ``messages`` list ordered by creation time.

    Raises:
        HTTPException: 401 if not authenticated, 404 if the
            conversation does not exist or belongs to another user,
            500 on database errors.
    """
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
        logger.error(f"Error getting messages for conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get messages")

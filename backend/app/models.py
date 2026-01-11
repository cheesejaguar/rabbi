"""Pydantic models for API request/response."""

from pydantic import BaseModel, Field
from typing import Optional


class Message(BaseModel):
    """A single message in the conversation."""
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str = Field(..., description="User's message", min_length=1)
    conversation_history: list[Message] = Field(
        default_factory=list,
        description="Previous messages in the conversation"
    )
    session_id: Optional[str] = Field(
        None,
        description="Optional session ID for tracking conversations"
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Optional conversation ID for persisting to database"
    )


class ChatResponse(BaseModel):
    """Response from the chat endpoint."""
    response: str = Field(..., description="Rabbi's response")
    requires_human_referral: bool = Field(
        False,
        description="Whether the user should be referred to a human rabbi"
    )
    session_id: Optional[str] = Field(None, description="Session ID")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")
    metadata: dict = Field(
        default_factory=dict,
        description="Additional metadata about the response"
    )


class GreetingResponse(BaseModel):
    """Response for the greeting endpoint."""
    greeting: str = Field(..., description="Initial greeting message")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")

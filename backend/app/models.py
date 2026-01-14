"""Pydantic models for API request/response."""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal


class Message(BaseModel):
    """A single message in the conversation."""
    role: Literal["user", "assistant"] = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content", max_length=50000)


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str = Field(..., description="User's message", min_length=1, max_length=10000)
    conversation_history: list[Message] = Field(
        default_factory=list,
        description="Previous messages in the conversation"
    )
    session_id: Optional[str] = Field(
        None,
        description="Optional session ID for tracking conversations",
        max_length=100
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Optional conversation ID for persisting to database",
        max_length=100
    )

    @field_validator('conversation_history')
    @classmethod
    def validate_history_length(cls, v):
        """Limit conversation history to prevent abuse."""
        if len(v) > 100:
            raise ValueError("Conversation history cannot exceed 100 messages")
        return v


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


class ProfileUpdate(BaseModel):
    """Request body for updating user profile."""
    denomination: Optional[str] = Field(
        None,
        description="User's Jewish denomination"
    )
    bio: Optional[str] = Field(
        None,
        description="User's bio (max 200 characters)",
        max_length=200
    )


class ProfileResponse(BaseModel):
    """Response for profile endpoint."""
    denomination: str = Field(..., description="User's Jewish denomination")
    bio: str = Field("", description="User's bio")

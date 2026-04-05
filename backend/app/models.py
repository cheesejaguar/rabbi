"""Pydantic v2 request/response models for the rebbe.dev REST API.

Provides input validation, serialization, and OpenAPI schema generation
for all API endpoints. Each model corresponds to a specific endpoint's
request body or response shape, ensuring that invalid data is rejected
before reaching business logic.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal


class Message(BaseModel):
    """A single message in the conversation history.

    Used within ``ChatRequest.conversation_history`` to replay prior
    turns for context. Content is capped at 50,000 characters to
    limit payload size.
    """

    role: Literal["user", "assistant"] = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content", max_length=50000)


class ChatRequest(BaseModel):
    """Request body for the ``POST /api/chat`` and ``POST /api/chat/stream`` endpoints.

    Carries the user's current message, the preceding conversation
    history, and optional tracking identifiers for session persistence.
    """

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
        """Limit conversation history to prevent abuse.

        The 100-message cap prevents context window abuse (sending
        extremely long histories to inflate LLM token usage) and
        keeps API costs bounded per request.
        """
        if len(v) > 100:
            raise ValueError("Conversation history cannot exceed 100 messages")
        return v


class ChatResponse(BaseModel):
    """Response body returned by the non-streaming ``POST /api/chat`` endpoint.

    Contains the rabbi's response text, a flag indicating whether the
    user should be referred to a human rabbi, and pipeline metadata
    (timing, token counts, etc.).
    """

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
    """Response body for the ``GET /api/greeting`` endpoint."""

    greeting: str = Field(..., description="Initial greeting message")


class HealthResponse(BaseModel):
    """Response body for the ``GET /api/health`` endpoint."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")


class ProfileUpdate(BaseModel):
    """Request body for the ``PUT /api/profile`` endpoint.

    Both fields are optional, allowing partial updates. The bio is
    constrained to 200 characters at the model layer.
    """

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
    """Response body for the ``GET /api/profile`` and ``PUT /api/profile`` endpoints."""

    denomination: Optional[str] = Field(default="just_jewish", description="User's Jewish denomination")
    bio: str = Field("", description="User's bio")


class DvarTorahResponse(BaseModel):
    """Response body for the ``GET /api/dvar-torah`` endpoint.

    Returns the weekly Torah commentary keyed by parsha and Hebrew year.
    When ``is_holiday_week`` is ``True``, no regular parsha is read and
    the content fields will be empty.
    """

    parsha_name: str = Field(..., description="English parsha name")
    parsha_name_hebrew: str = Field("", description="Hebrew parsha name")
    hebrew_year: int = Field(0, description="Hebrew calendar year")
    content: str = Field("", description="The d'var Torah text")
    is_holiday_week: bool = Field(False, description="True when no regular parsha is read")

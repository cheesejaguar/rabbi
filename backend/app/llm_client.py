"""Simple LLM client using httpx instead of the openai SDK.

This replaces the openai SDK to reduce dependencies. It provides the same
interface for chat completions that we actually use.
"""

import httpx
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Usage:
    """Token usage from an API response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Message:
    """A message in a chat completion."""
    content: str
    role: str = "assistant"


@dataclass
class Choice:
    """A choice in a chat completion response."""
    message: Message
    index: int = 0
    finish_reason: str = "stop"


@dataclass
class Delta:
    """A delta in a streaming chunk."""
    content: Optional[str] = None
    role: Optional[str] = None


@dataclass
class StreamChoice:
    """A choice in a streaming chunk."""
    delta: Delta
    index: int = 0
    finish_reason: Optional[str] = None


@dataclass
class ChatCompletion:
    """A chat completion response."""
    choices: list[Choice]
    usage: Optional[Usage] = None
    id: str = ""
    model: str = ""


@dataclass
class ChatCompletionChunk:
    """A streaming chunk from the API."""
    choices: list[StreamChoice]
    usage: Optional[Usage] = None
    id: str = ""
    model: str = ""


class ChatCompletions:
    """Chat completions API interface."""

    def __init__(self, client: "LLMClient"):
        self._client = client

    def create(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 2048,
        stream: bool = False,
        stream_options: Optional[dict] = None,
        **kwargs,
    ) -> ChatCompletion | Iterator[ChatCompletionChunk]:
        """Create a chat completion (blocking or streaming)."""
        if stream:
            return self._create_stream(model, messages, max_tokens, stream_options)
        return self._create_blocking(model, messages, max_tokens)

    def _create_blocking(
        self, model: str, messages: list[dict], max_tokens: int
    ) -> ChatCompletion:
        """Create a blocking chat completion."""
        response = self._client._http_client.post(
            f"{self._client.base_url}/chat/completions",
            headers=self._client._headers(),
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()

        usage = None
        if "usage" in data:
            usage = Usage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=data["usage"].get("completion_tokens", 0),
                total_tokens=data["usage"].get("total_tokens", 0),
            )

        choices = []
        for choice_data in data.get("choices", []):
            message_data = choice_data.get("message", {})
            choices.append(
                Choice(
                    message=Message(
                        content=message_data.get("content", ""),
                        role=message_data.get("role", "assistant"),
                    ),
                    index=choice_data.get("index", 0),
                    finish_reason=choice_data.get("finish_reason", "stop"),
                )
            )

        return ChatCompletion(
            choices=choices,
            usage=usage,
            id=data.get("id", ""),
            model=data.get("model", model),
        )

    def _create_stream(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        stream_options: Optional[dict] = None,
    ) -> Iterator[ChatCompletionChunk]:
        """Create a streaming chat completion."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if stream_options:
            payload["stream_options"] = stream_options

        with self._client._http_client.stream(
            "POST",
            f"{self._client.base_url}/chat/completions",
            headers=self._client._headers(),
            json=payload,
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str == "[DONE]":
                        break
                    try:
                        import json
                        data = json.loads(data_str)
                        yield self._parse_chunk(data)
                    except (json.JSONDecodeError, KeyError):
                        continue

    def _parse_chunk(self, data: dict) -> ChatCompletionChunk:
        """Parse a streaming chunk from JSON data."""
        usage = None
        if "usage" in data and data["usage"]:
            usage = Usage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=data["usage"].get("completion_tokens", 0),
                total_tokens=data["usage"].get("total_tokens", 0),
            )

        choices = []
        for choice_data in data.get("choices", []):
            delta_data = choice_data.get("delta", {})
            choices.append(
                StreamChoice(
                    delta=Delta(
                        content=delta_data.get("content"),
                        role=delta_data.get("role"),
                    ),
                    index=choice_data.get("index", 0),
                    finish_reason=choice_data.get("finish_reason"),
                )
            )

        return ChatCompletionChunk(
            choices=choices,
            usage=usage,
            id=data.get("id", ""),
            model=data.get("model", ""),
        )


class Chat:
    """Chat API namespace."""

    def __init__(self, client: "LLMClient"):
        self.completions = ChatCompletions(client)


class LLMClient:
    """Simple LLM client compatible with OpenAI API.

    This is a drop-in replacement for the openai.OpenAI client,
    implementing only the methods we actually use.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http_client = httpx.Client()
        self.chat = Chat(self)

    def _headers(self) -> dict:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def close(self):
        """Close the HTTP client."""
        self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

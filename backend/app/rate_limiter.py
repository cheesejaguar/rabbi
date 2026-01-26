"""Simple in-memory rate limiter to replace slowapi.

This provides basic rate limiting functionality without the overhead
of supporting Redis, Memcached, and other backends we don't use.
"""

import time
import re
from collections import defaultdict
from functools import wraps
from typing import Callable, Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, detail: str = "Rate limit exceeded", retry_after: int = 60):
        self.detail = detail
        self.retry_after = retry_after
        super().__init__(detail)


class RateLimiter:
    """Simple in-memory rate limiter.

    Tracks request timestamps per key and enforces rate limits
    using a sliding window algorithm.
    """

    def __init__(self, key_func: Callable[[Request], str]):
        """Initialize the rate limiter.

        Args:
            key_func: Function that extracts the rate limit key from a request
        """
        self.key_func = key_func
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._cleanup_counter = 0
        self._cleanup_interval = 100  # Cleanup every N requests

    def _parse_limit(self, limit_string: str) -> tuple[int, int]:
        """Parse a limit string like '30/minute' into (count, window_seconds).

        Supports: /second, /minute, /hour, /day
        """
        match = re.match(r"(\d+)/(\w+)", limit_string)
        if not match:
            raise ValueError(f"Invalid rate limit format: {limit_string}")

        count = int(match.group(1))
        period = match.group(2).lower()

        windows = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }

        if period not in windows:
            raise ValueError(f"Unknown time period: {period}")

        return count, windows[period]

    def _cleanup_old_entries(self, now: float):
        """Remove old entries to prevent memory growth."""
        # Only cleanup periodically
        self._cleanup_counter += 1
        if self._cleanup_counter < self._cleanup_interval:
            return

        self._cleanup_counter = 0
        max_window = 86400  # Keep at most 1 day of history

        keys_to_delete = []
        for key, timestamps in self._requests.items():
            # Remove timestamps older than max_window
            self._requests[key] = [t for t in timestamps if now - t < max_window]
            if not self._requests[key]:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._requests[key]

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Check if a request is allowed under the rate limit.

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        now = time.time()
        self._cleanup_old_entries(now)

        # Get timestamps within the window
        window_start = now - window_seconds
        timestamps = self._requests[key]
        recent = [t for t in timestamps if t > window_start]

        if len(recent) >= limit:
            # Calculate retry-after based on oldest timestamp in window
            oldest_in_window = min(recent)
            retry_after = int(oldest_in_window + window_seconds - now) + 1
            return False, max(retry_after, 1)

        # Allow the request and record timestamp
        recent.append(now)
        self._requests[key] = recent
        return True, 0

    def limit(self, limit_string: str):
        """Decorator to apply rate limiting to an endpoint.

        Usage:
            @limiter.limit("30/minute")
            async def my_endpoint(request: Request):
                ...
        """
        limit_count, window_seconds = self._parse_limit(limit_string)

        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Find the Request object in args or kwargs
                request = None
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
                if request is None:
                    request = kwargs.get("request")

                if request is None:
                    # No request object found, skip rate limiting
                    return await func(*args, **kwargs)

                key = self.key_func(request)
                allowed, retry_after = self.is_allowed(key, limit_count, window_seconds)

                if not allowed:
                    raise RateLimitExceeded(
                        detail=f"Rate limit exceeded: {limit_string}",
                        retry_after=retry_after,
                    )

                return await func(*args, **kwargs)

            return wrapper

        return decorator


def get_remote_address(request: Request) -> str:
    """Extract the client IP address from a request.

    Handles X-Forwarded-For header for proxied requests.
    """
    # Check for forwarded header (common with reverse proxies)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP in the chain (original client)
        return forwarded.split(",")[0].strip()

    # Fall back to direct client address
    if request.client:
        return request.client.host

    return "unknown"


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """FastAPI exception handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please slow down.",
            "retry_after": exc.retry_after,
        },
        headers={"Retry-After": str(exc.retry_after)},
    )

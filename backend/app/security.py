"""Security hardening module for guest abuse prevention and input validation."""

import hashlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional
from fastapi import Request

from .config import get_settings

logger = logging.getLogger(__name__)

# Get configuration from settings
_settings = get_settings()

# Configuration constants (loaded from settings with defaults)
GUEST_IP_CHAT_LIMIT = _settings.guest_ip_chat_limit  # Max chats per IP per day
IP_BLOCK_THRESHOLD = _settings.ip_block_threshold  # Number of violations before IP is blocked
IP_BLOCK_DURATION = _settings.ip_block_duration  # Block duration in seconds
RATE_LIMIT_WINDOW = 60  # Rate limit window in seconds
GUEST_RATE_LIMIT_PER_MINUTE = _settings.guest_rate_limit_per_minute  # Max requests per minute for guests
MAX_MESSAGE_LENGTH = _settings.max_message_length  # Maximum characters in a chat message
MIN_MESSAGE_LENGTH = 1  # Minimum characters in a chat message
CLEANUP_INTERVAL = 300  # Cleanup old entries every 5 minutes


@dataclass
class IPTracker:
    """Track IP-based activity for abuse prevention."""

    chat_count: int = 0
    last_chat_time: float = 0
    violation_count: int = 0
    blocked_until: float = 0
    request_timestamps: list = field(default_factory=list)
    fingerprints: set = field(default_factory=set)
    first_seen: float = field(default_factory=time.time)


class GuestSecurityManager:
    """Manages guest security tracking and abuse prevention.

    Uses in-memory storage with TTL-based cleanup. For production
    deployments with multiple instances, consider using Redis.
    """

    def __init__(self):
        self._ip_data: dict[str, IPTracker] = defaultdict(IPTracker)
        self._lock = Lock()
        self._last_cleanup = time.time()

    def _cleanup_old_entries(self):
        """Remove expired entries to prevent memory bloat."""
        current_time = time.time()
        if current_time - self._last_cleanup < CLEANUP_INTERVAL:
            return

        with self._lock:
            self._last_cleanup = current_time
            # Remove entries older than 24 hours with no recent activity
            cutoff = current_time - 86400
            to_remove = [
                ip for ip, data in self._ip_data.items()
                if data.last_chat_time < cutoff and data.blocked_until < current_time
            ]
            for ip in to_remove:
                del self._ip_data[ip]
            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} expired IP tracking entries")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, accounting for proxies."""
        # Check X-Forwarded-For header (set by reverse proxies)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Take the first IP (original client)
            return forwarded.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        # Fall back to direct client IP
        if request.client:
            return request.client.host
        return "unknown"

    def generate_fingerprint(self, request: Request) -> str:
        """Generate a device fingerprint from request headers.

        This provides an additional layer of tracking beyond cookies.
        Not foolproof, but raises the bar for abuse.
        """
        components = [
            request.headers.get("user-agent", ""),
            request.headers.get("accept-language", ""),
            request.headers.get("accept-encoding", ""),
            request.headers.get("accept", ""),
            # Screen info might be sent by frontend
            request.headers.get("x-screen-info", ""),
        ]
        fingerprint_str = "|".join(components)
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]

    def is_ip_blocked(self, request: Request) -> tuple[bool, Optional[str]]:
        """Check if the client IP is blocked.

        Returns (is_blocked, reason).
        """
        self._cleanup_old_entries()
        ip = self._get_client_ip(request)

        with self._lock:
            tracker = self._ip_data[ip]
            current_time = time.time()

            if tracker.blocked_until > current_time:
                remaining = int(tracker.blocked_until - current_time)
                return True, f"IP temporarily blocked. Try again in {remaining} seconds."

        return False, None

    def check_rate_limit(self, request: Request) -> tuple[bool, Optional[str]]:
        """Check if guest request rate is within limits.

        Returns (is_allowed, error_message).
        """
        ip = self._get_client_ip(request)
        current_time = time.time()

        with self._lock:
            tracker = self._ip_data[ip]

            # Clean old timestamps
            tracker.request_timestamps = [
                ts for ts in tracker.request_timestamps
                if current_time - ts < RATE_LIMIT_WINDOW
            ]

            if len(tracker.request_timestamps) >= GUEST_RATE_LIMIT_PER_MINUTE:
                self._record_violation(tracker, ip, "rate_limit_exceeded")
                return False, "Too many requests. Please slow down."

            tracker.request_timestamps.append(current_time)

        return True, None

    def check_guest_chat_allowed(self, request: Request, cookie_count: int) -> tuple[bool, Optional[str]]:
        """Check if guest is allowed to chat based on IP tracking.

        This provides a secondary check beyond the cookie-based tracking.
        Returns (is_allowed, error_message).
        """
        ip = self._get_client_ip(request)
        fingerprint = self.generate_fingerprint(request)
        current_time = time.time()

        with self._lock:
            tracker = self._ip_data[ip]

            # Check if IP is blocked
            if tracker.blocked_until > current_time:
                remaining = int(tracker.blocked_until - current_time)
                return False, f"Access temporarily restricted. Try again in {remaining} seconds."

            # Check for suspicious fingerprint patterns
            # Multiple different fingerprints from same IP within short time = potential abuse
            tracker.fingerprints.add(fingerprint)
            if len(tracker.fingerprints) > 5:  # More than 5 different fingerprints
                logger.warning(f"Suspicious fingerprint pattern from IP {ip}: {len(tracker.fingerprints)} fingerprints")
                self._record_violation(tracker, ip, "fingerprint_anomaly")

            # Reset daily counter if it's a new day
            if current_time - tracker.first_seen > 86400:
                tracker.chat_count = 0
                tracker.first_seen = current_time
                tracker.fingerprints.clear()

            # Check IP-based chat limit
            # This catches users who clear cookies
            if tracker.chat_count >= GUEST_IP_CHAT_LIMIT:
                logger.info(f"IP {ip} exceeded daily guest chat limit ({tracker.chat_count} chats)")
                return False, "Daily limit reached. Please sign in to continue."

            # If cookie says 0 but IP tracker shows activity, that's suspicious
            if cookie_count == 0 and tracker.chat_count > 0:
                logger.warning(f"Cookie cleared detected for IP {ip}: cookie=0, ip_count={tracker.chat_count}")
                self._record_violation(tracker, ip, "cookie_cleared")
                # Use IP count as the authoritative count
                if tracker.chat_count >= GUEST_IP_CHAT_LIMIT:
                    return False, "Daily limit reached. Please sign in to continue."

        return True, None

    def record_guest_chat(self, request: Request):
        """Record that a guest chat occurred from this IP."""
        ip = self._get_client_ip(request)
        current_time = time.time()

        with self._lock:
            tracker = self._ip_data[ip]
            tracker.chat_count += 1
            tracker.last_chat_time = current_time

        logger.debug(f"Recorded guest chat from IP {ip}, total: {tracker.chat_count}")

    def _record_violation(self, tracker: IPTracker, ip: str, violation_type: str):
        """Record a security violation and potentially block the IP."""
        tracker.violation_count += 1
        logger.warning(f"Security violation from IP {ip}: {violation_type} (count: {tracker.violation_count})")

        if tracker.violation_count >= IP_BLOCK_THRESHOLD:
            tracker.blocked_until = time.time() + IP_BLOCK_DURATION
            logger.warning(f"IP {ip} blocked for {IP_BLOCK_DURATION} seconds due to repeated violations")

    def get_effective_guest_count(self, request: Request, cookie_count: int) -> int:
        """Get the effective guest chat count, using the higher of cookie or IP count.

        This prevents abuse by cookie clearing.
        """
        ip = self._get_client_ip(request)

        with self._lock:
            tracker = self._ip_data[ip]
            return max(cookie_count, tracker.chat_count)

    def log_suspicious_activity(self, request: Request, activity_type: str, details: str = ""):
        """Log suspicious activity for monitoring."""
        ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        logger.warning(
            f"Suspicious activity detected - Type: {activity_type}, "
            f"IP: {ip}, UA: {user_agent[:100]}, Details: {details}"
        )


class InputValidator:
    """Validate and sanitize user input."""

    # Patterns that might indicate prompt injection or abuse
    SUSPICIOUS_PATTERNS = [
        "ignore previous instructions",
        "ignore all previous",
        "disregard your instructions",
        "you are now",
        "pretend to be",
        "act as if",
        "system prompt",
        "reveal your prompt",
        "show me your instructions",
        "what are your rules",
        "bypass your",
        "jailbreak",
        "dan mode",
        "developer mode",
        "ignore your programming",
    ]

    @classmethod
    def validate_message(cls, message: str) -> tuple[bool, Optional[str]]:
        """Validate a chat message.

        Returns (is_valid, error_message).
        """
        if not message:
            return False, "Message cannot be empty"

        if len(message) < MIN_MESSAGE_LENGTH:
            return False, f"Message must be at least {MIN_MESSAGE_LENGTH} character(s)"

        if len(message) > MAX_MESSAGE_LENGTH:
            return False, f"Message exceeds maximum length of {MAX_MESSAGE_LENGTH} characters"

        # Check for suspicious patterns (case-insensitive)
        message_lower = message.lower()
        for pattern in cls.SUSPICIOUS_PATTERNS:
            if pattern in message_lower:
                logger.warning(f"Suspicious pattern detected in message: {pattern}")
                # Don't block but log for monitoring
                # The LLM should handle these gracefully
                break

        return True, None

    @classmethod
    def sanitize_message(cls, message: str) -> str:
        """Sanitize a message by removing potentially harmful content.

        Note: This is a light sanitization. The LLM handles most content filtering.
        """
        # Remove null bytes and other control characters (except newlines/tabs)
        sanitized = "".join(
            char for char in message
            if char == '\n' or char == '\t' or (ord(char) >= 32 and ord(char) != 127)
        )

        # Trim excessive whitespace
        lines = sanitized.split('\n')
        lines = [line.strip() for line in lines]
        # Remove excessive blank lines (more than 2 consecutive)
        result_lines = []
        blank_count = 0
        for line in lines:
            if not line:
                blank_count += 1
                if blank_count <= 2:
                    result_lines.append(line)
            else:
                blank_count = 0
                result_lines.append(line)

        return '\n'.join(result_lines).strip()


# Global instance for use across the application
guest_security = GuestSecurityManager()
input_validator = InputValidator()

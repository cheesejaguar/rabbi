"""Guest abuse prevention system with three-layer defense.

This module implements a multi-layered security strategy to prevent abuse of
the guest (unauthenticated) chat feature:

    1. **IP-based rate tracking**: Monitors chat frequency and daily totals per
       client IP address, surviving cookie clears and browser switches.
    2. **Signed cookie verification**: Cross-references server-side IP counts
       with client-side signed cookies to detect cookie-clearing attempts.
    3. **Browser fingerprint anomaly detection**: Hashes request headers into a
       device fingerprint; an unusual number of distinct fingerprints from one
       IP suggests automated tooling or deliberate evasion.

Violations from any layer are accumulated per IP. Once the violation count
reaches ``IP_BLOCK_THRESHOLD``, the IP is temporarily blocked for
``IP_BLOCK_DURATION`` seconds.

Note:
    This module uses in-memory storage (``defaultdict`` + ``Lock``). In a
    multi-instance production deployment behind a load balancer, a shared
    store such as Redis should replace the in-memory dicts.
"""

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

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class IPTracker:
    """Per-IP tracking state for guest abuse prevention.

    Attributes:
        chat_count: Number of guest chats recorded from this IP in the
            current 24-hour window.
        last_chat_time: Unix timestamp of the most recent chat from this IP.
        violation_count: Cumulative number of security violations (rate-limit
            exceeded, fingerprint anomaly, cookie tampering). When this reaches
            ``IP_BLOCK_THRESHOLD`` the IP is temporarily blocked.
        blocked_until: Unix timestamp until which this IP is blocked. A value
            of ``0`` means the IP is not currently blocked.
        request_timestamps: Rolling list of recent request timestamps used for
            per-minute rate limiting (entries older than ``RATE_LIMIT_WINDOW``
            are pruned on each check).
        fingerprints: Set of distinct browser fingerprint hashes observed from
            this IP. More than 5 unique fingerprints in a 24-hour window
            triggers a fingerprint anomaly violation.
        first_seen: Unix timestamp when this IP was first recorded. Used to
            determine when to reset the daily counter (after 86 400 seconds).
    """

    chat_count: int = 0
    last_chat_time: float = 0
    violation_count: int = 0
    blocked_until: float = 0
    request_timestamps: list = field(default_factory=list)
    fingerprints: set = field(default_factory=set)
    first_seen: float = field(default_factory=time.time)

# ---------------------------------------------------------------------------
# Guest Tracking
# ---------------------------------------------------------------------------


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
        """Remove expired entries to prevent memory bloat.

        Runs at most once every ``CLEANUP_INTERVAL`` seconds (300 s).
        Entries are considered expired when their last chat was more than
        24 hours ago (86 400 s) **and** they are not currently blocked.
        """
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
        """Extract the originating client IP address from a request.

        Checks proxy headers in priority order to handle reverse-proxy
        deployments (e.g., behind nginx or a cloud load balancer):

        1. ``X-Forwarded-For`` -- takes the *first* (leftmost) IP, which is
           the original client per the de-facto standard.
        2. ``X-Real-IP`` -- single-IP header set by some proxies.
        3. Direct ``request.client.host`` as a last resort.

        Args:
            request: The incoming FastAPI ``Request`` object.

        Returns:
            A string representing the client IP address, or ``"unknown"`` if
            no address can be determined.
        """
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

        Produces a truncated SHA-256 hash of concatenated header values.
        This provides an additional layer of tracking beyond cookies --
        not foolproof (headers can be spoofed), but raises the bar for
        casual abuse.

        Args:
            request: The incoming FastAPI ``Request`` object.

        Returns:
            A 16-character hex string representing the fingerprint hash.
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
        """Check if the client IP is currently blocked.

        Args:
            request: The incoming FastAPI ``Request`` object.

        Returns:
            A tuple of ``(is_blocked, reason)``. ``reason`` is a
            human-readable message when blocked, or ``None`` otherwise.
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
        """Check if the guest request rate is within per-minute limits.

        Maintains a sliding window of ``RATE_LIMIT_WINDOW`` seconds (60 s).
        If the number of requests in that window reaches
        ``GUEST_RATE_LIMIT_PER_MINUTE``, a rate-limit violation is recorded.

        Args:
            request: The incoming FastAPI ``Request`` object.

        Returns:
            A tuple of ``(is_allowed, error_message)``. ``error_message``
            is ``None`` when the request is within limits.
        """
        ip = self._get_client_ip(request)
        current_time = time.time()

        with self._lock:
            tracker = self._ip_data[ip]

            # Clean old timestamps outside the sliding window
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
        """Determine whether a guest chat request should be permitted.

        Implements the three-layer defense strategy:

        **Layer 1 -- IP block check**: If this IP has accumulated too many
        violations and is currently blocked, deny immediately.

        **Layer 2 -- Fingerprint anomaly detection**: Each unique browser
        fingerprint from this IP is recorded. If more than 5 distinct
        fingerprints are seen within a 24-hour window, a violation is logged.
        This catches users rotating browsers or using automation tooling.

        **Layer 3 -- Daily limit & cookie cross-reference**: The IP-based
        ``chat_count`` is compared against ``GUEST_IP_CHAT_LIMIT``. If the
        signed cookie reports 0 chats but the IP tracker shows prior
        activity, the user likely cleared their cookies to reset the count --
        a violation is recorded and the IP count is treated as authoritative.

        The daily counter resets after 86 400 seconds (24 hours) from
        ``first_seen``, at which point fingerprints are also cleared.

        Args:
            request: The incoming FastAPI ``Request`` object.
            cookie_count: The guest chat count reported by the client's
                signed cookie (may be 0 if cookie was cleared/tampered).

        Returns:
            A tuple of ``(is_allowed, error_message)``. ``error_message``
            is ``None`` when the request is permitted.
        """
        ip = self._get_client_ip(request)
        fingerprint = self.generate_fingerprint(request)
        current_time = time.time()

        with self._lock:
            tracker = self._ip_data[ip]

            # --- Layer 1: IP block check ---
            if tracker.blocked_until > current_time:
                remaining = int(tracker.blocked_until - current_time)
                return False, f"Access temporarily restricted. Try again in {remaining} seconds."

            # --- Layer 2: Fingerprint anomaly detection ---
            # Multiple different fingerprints from same IP within short time = potential abuse
            tracker.fingerprints.add(fingerprint)
            # Threshold: more than 5 distinct fingerprints triggers a warning
            if len(tracker.fingerprints) > 5:
                logger.warning(f"Suspicious fingerprint pattern from IP {ip}: {len(tracker.fingerprints)} fingerprints")
                self._record_violation(tracker, ip, "fingerprint_anomaly")

            # --- Daily reset at 86 400 seconds (24 hours) ---
            if current_time - tracker.first_seen > 86400:
                tracker.chat_count = 0
                tracker.first_seen = current_time
                tracker.fingerprints.clear()

            # --- Layer 3: Daily chat limit & cookie cross-reference ---
            # Check IP-based chat limit (catches users who clear cookies)
            if tracker.chat_count >= GUEST_IP_CHAT_LIMIT:
                logger.info(f"IP {ip} exceeded daily guest chat limit ({tracker.chat_count} chats)")
                return False, "Daily limit reached. Please sign in to continue."

            # If cookie says 0 but IP tracker shows activity, that's suspicious
            # -- the user likely cleared cookies to reset their guest allowance
            if cookie_count == 0 and tracker.chat_count > 0:
                logger.warning(f"Cookie cleared detected for IP {ip}: cookie=0, ip_count={tracker.chat_count}")
                self._record_violation(tracker, ip, "cookie_cleared")
                # Use IP count as the authoritative count
                if tracker.chat_count >= GUEST_IP_CHAT_LIMIT:
                    return False, "Daily limit reached. Please sign in to continue."

        return True, None

    def record_guest_chat(self, request: Request):
        """Record that a guest chat occurred from this IP.

        Increments the IP's daily chat counter and updates the last-chat
        timestamp. Called after a guest chat message is successfully
        processed.

        Args:
            request: The incoming FastAPI ``Request`` object.
        """
        ip = self._get_client_ip(request)
        current_time = time.time()

        with self._lock:
            tracker = self._ip_data[ip]
            tracker.chat_count += 1
            tracker.last_chat_time = current_time

        logger.debug(f"Recorded guest chat from IP {ip}, total: {tracker.chat_count}")

    def _record_violation(self, tracker: IPTracker, ip: str, violation_type: str):
        """Record a security violation and potentially block the IP.

        Each call increments ``violation_count``. When the count reaches
        ``IP_BLOCK_THRESHOLD``, the IP is blocked for ``IP_BLOCK_DURATION``
        seconds.

        Args:
            tracker: The ``IPTracker`` instance for this IP.
            ip: The client IP address string (for logging).
            violation_type: A short label describing the violation
                (e.g., ``"rate_limit_exceeded"``, ``"fingerprint_anomaly"``,
                ``"cookie_cleared"``).
        """
        tracker.violation_count += 1
        logger.warning(f"Security violation from IP {ip}: {violation_type} (count: {tracker.violation_count})")

        if tracker.violation_count >= IP_BLOCK_THRESHOLD:
            tracker.blocked_until = time.time() + IP_BLOCK_DURATION
            logger.warning(f"IP {ip} blocked for {IP_BLOCK_DURATION} seconds due to repeated violations")

    def get_effective_guest_count(self, request: Request, cookie_count: int) -> int:
        """Get the effective guest chat count, using the higher of cookie or IP count.

        This prevents abuse by cookie clearing -- if the IP tracker has
        recorded more chats than the cookie reports, the IP count takes
        precedence.

        Args:
            request: The incoming FastAPI ``Request`` object.
            cookie_count: The guest chat count reported by the client's
                signed cookie.

        Returns:
            The higher of ``cookie_count`` and the server-side IP chat count.
        """
        ip = self._get_client_ip(request)

        with self._lock:
            tracker = self._ip_data[ip]
            return max(cookie_count, tracker.chat_count)

    def log_suspicious_activity(self, request: Request, activity_type: str, details: str = ""):
        """Log suspicious activity for monitoring and forensic review.

        This is a logging-only method; it does not block requests or
        record violations.

        Args:
            request: The incoming FastAPI ``Request`` object.
            activity_type: A short label categorizing the activity
                (e.g., ``"unusual_payload"``, ``"rapid_reconnect"``).
            details: Optional free-text description with additional context.
        """
        ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        logger.warning(
            f"Suspicious activity detected - Type: {activity_type}, "
            f"IP: {ip}, UA: {user_agent[:100]}, Details: {details}"
        )

# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class InputValidator:
    """Validate and sanitize user input before it reaches the LLM pipeline."""

    # Patterns that might indicate prompt injection or abuse.
    #
    # IMPORTANT: These patterns are used for *detection and logging only*.
    # Matching a pattern does NOT block the message. The LLM's own system
    # prompt contains robust instructions for handling prompt injection
    # attempts gracefully. This list exists so that suspicious attempts are
    # recorded in application logs for monitoring and incident response.
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
        """Validate a chat message against length and content rules.

        Checks minimum/maximum length constraints and scans for suspicious
        prompt-injection patterns (logged but not blocked).

        Args:
            message: The raw user message string.

        Returns:
            A tuple of ``(is_valid, error_message)``. ``error_message`` is
            ``None`` when the message passes validation.
        """
        if not message:
            return False, "Message cannot be empty"

        if len(message) < MIN_MESSAGE_LENGTH:
            return False, f"Message must be at least {MIN_MESSAGE_LENGTH} character(s)"

        if len(message) > MAX_MESSAGE_LENGTH:
            return False, f"Message exceeds maximum length of {MAX_MESSAGE_LENGTH} characters"

        # Check for suspicious patterns (case-insensitive).
        # Matches are logged for monitoring but the message is NOT blocked --
        # the LLM's system prompt handles prompt injection defense.
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

        Performs light sanitization only -- the LLM pipeline handles most
        content filtering. This method:

        * Strips null bytes and non-printable control characters (preserving
          newlines and tabs).
        * Collapses runs of more than two consecutive blank lines.
        * Trims leading/trailing whitespace from each line and the overall
          result.

        Args:
            message: The raw user message string.

        Returns:
            The sanitized message string.
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

# ---------------------------------------------------------------------------
# Abuse Detection -- module-level singletons
# ---------------------------------------------------------------------------

# Global instance for use across the application
guest_security = GuestSecurityManager()
input_validator = InputValidator()

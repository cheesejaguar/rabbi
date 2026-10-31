"""Rate limits and guest caps that hold across serverless instances.

Counters live in Postgres (``rate_limits`` table) so every Vercel instance
sees the same numbers. Without a database (local dev, tests) or if the
database errors, an in-process fallback is used: availability is preferred
over strictness for rate limits, while the credit system itself fails closed.
"""

import logging
import os
import threading
import time

from fastapi import Request

from . import database as db
from .config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_mem: dict[str, tuple[float, int]] = {}


def _mem_hit(key: str, window: int, amount: int) -> int:
    now = time.time()
    with _lock:
        start, count = _mem.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        count += amount
        _mem[key] = (start, count)
        if len(_mem) > 50_000:  # bound memory
            for k in list(_mem)[:10_000]:
                _mem.pop(k, None)
        return count


def _mem_peek(key: str, window: int) -> int:
    now = time.time()
    with _lock:
        start, count = _mem.get(key, (now, 0))
        return 0 if now - start >= window else count


async def hit(key: str, window: int, amount: int = 1) -> int:
    if get_settings().db_url:
        try:
            return await db.rate_limit_hit(key, window, amount)
        except Exception as e:
            logger.warning("rate_limit_hit fell back to memory: %s", e)
    return _mem_hit(key, window, amount)


async def peek(key: str, window: int) -> int:
    if get_settings().db_url:
        try:
            return await db.rate_limit_peek(key, window)
        except Exception as e:
            logger.warning("rate_limit_peek fell back to memory: %s", e)
    return _mem_peek(key, window)


def _trust_forwarded() -> bool:
    # Vercel overwrites X-Forwarded-For with the real client address, so it is
    # trustworthy there. Elsewhere (e.g. Docker) it is client-controlled unless
    # a trusted proxy is configured with TRUST_FORWARDED_FOR=true.
    return bool(os.environ.get("VERCEL")) or get_settings().trust_forwarded_for


def client_ip(request: Request) -> str:
    if _trust_forwarded():
        real = request.headers.get("x-real-ip", "").strip()
        if real:
            return real[:64]
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            # Behind a trusted proxy, the right-most entry is the hop it appended.
            return fwd.split(",")[-1].strip()[:64] if not os.environ.get("VERCEL") else fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


PENALTY_WINDOW = 3600
PENALTY_BLOCK_AT = 5


async def is_blocked(ip: str) -> bool:
    return await peek(f"penalty:{ip}", PENALTY_WINDOW) >= PENALTY_BLOCK_AT


async def add_penalty(ip: str, amount: int = 1) -> None:
    await hit(f"penalty:{ip}", PENALTY_WINDOW, amount)


async def check_chat_rate(request: Request, user_id: str | None) -> bool:
    s = get_settings()
    if user_id:
        return await hit(f"chat:u:{user_id}", 60) <= s.rate_limit_chat_per_minute
    return await hit(f"chat:ip:{client_ip(request)}", 60) <= s.guest_rate_limit_per_minute


async def guest_ip_count(request: Request) -> int:
    return await peek(f"guest:ip:{client_ip(request)}", 86400)


async def record_guest_turn(request: Request) -> None:
    await hit(f"guest:ip:{client_ip(request)}", 86400)

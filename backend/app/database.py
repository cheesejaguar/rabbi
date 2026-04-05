"""Async PostgreSQL database layer for rebbe.dev.

Provides connection pooling, schema auto-migration, and all CRUD operations
for the application's data model. Key characteristics:

- **asyncpg** for high-performance async Postgres access.
- **Vercel / Neon Postgres compatible** -- automatically appends
  ``sslmode=require`` when connecting to hosted databases.
- **Connection pooling** via ``asyncpg.Pool`` (1-10 connections).
- **Schema auto-migration** with PostgreSQL advisory locks so that
  concurrent serverless cold-starts don't race on DDL.

Typical usage::

    from . import database as db
    await db.init_schema()          # called once at startup
    user = await db.upsert_user(...)
    await db.close_pool()           # called at shutdown
"""

import asyncio
import asyncpg
from typing import Optional
from contextlib import asynccontextmanager

from .config import get_settings

# Global connection pool -- lazily initialized on first use.
# The asyncio.Lock prevents multiple concurrent callers from creating
# duplicate pools during the first cold-start.
_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Connection Management
# ---------------------------------------------------------------------------


async def get_pool() -> asyncpg.Pool:
    """Return the global asyncpg connection pool, creating it if necessary.

    Uses a double-checked locking pattern: a fast non-locked check followed
    by an ``asyncio.Lock``-guarded initialization to prevent duplicate pools
    when multiple serverless invocations cold-start simultaneously.

    Returns:
        The shared ``asyncpg.Pool`` instance.

    Raises:
        RuntimeError: If no database URL is configured (neither
            ``POSTGRES_URL`` nor ``DATABASE_URL`` is set).
    """
    global _pool

    # Fast path: pool already initialized
    if _pool is not None:
        return _pool

    # Slow path: initialize pool with async lock to prevent races
    async with _pool_lock:
        if _pool is None:
            settings = get_settings()
            if not settings.db_url:
                raise RuntimeError("Database URL not configured. Set POSTGRES_URL or DATABASE_URL.")

            # Neon/Vercel Postgres requires SSL; append if not already present
            db_url = settings.db_url
            if "sslmode" not in db_url:
                db_url = f"{db_url}?sslmode=require" if "?" not in db_url else f"{db_url}&sslmode=require"

            _pool = await asyncpg.create_pool(
                db_url,
                min_size=1,   # Keep at least one warm connection
                max_size=10,  # Upper bound for concurrent queries
                command_timeout=60,
            )
        return _pool


async def close_pool():
    """Gracefully close all connections in the pool.

    Safe to call multiple times. Typically invoked during application
    shutdown via the FastAPI lifespan handler.
    """
    global _pool
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None


@asynccontextmanager
async def get_connection():
    """Acquire a single connection from the pool as an async context manager.

    Yields:
        An ``asyncpg.Connection`` that is automatically released back to the
        pool when the ``async with`` block exits.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Schema Initialization
# ---------------------------------------------------------------------------

# The complete DDL for all application tables, indexes, triggers, and
# safe column migrations. Executed once at startup via init_schema().
SCHEMA_SQL = """
-- =========================================================================
-- USERS TABLE
-- Core user record, synced from WorkOS on login. The 'id' is the WorkOS
-- user ID (opaque string). New users start with 3 free credits.
-- =========================================================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,                       -- WorkOS user ID
    email TEXT UNIQUE NOT NULL,
    first_name TEXT,
    last_name TEXT,
    credits INTEGER DEFAULT 3,                 -- Chat credits remaining
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Safe migration: add credits column for databases created before the
-- credits system was introduced.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'users' AND column_name = 'credits') THEN
        ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 3;
    END IF;
END $$;

-- =========================================================================
-- CONVERSATIONS TABLE
-- Groups messages into named threads owned by a single user. Deleting a
-- user cascades to delete all their conversations.
-- =========================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,                                 -- Auto-generated from first message
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =========================================================================
-- MESSAGES TABLE
-- Individual chat messages within a conversation. 'role' is constrained
-- to 'user' or 'assistant'. Metadata stores pipeline metrics for
-- assistant messages.
-- =========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',               -- Pipeline timing, token counts, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index: list conversations by user, sorted by most-recently-active
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
-- Index: sidebar "recent conversations" query
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);
-- Index: load messages for a conversation
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
-- Index: chronological message ordering
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- =========================================================================
-- TRIGGER FUNCTIONS
-- =========================================================================

-- Generic trigger function: sets updated_at = NOW() before any UPDATE.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Auto-update users.updated_at on every row update.
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Auto-update conversations.updated_at on every row update.
DROP TRIGGER IF EXISTS update_conversations_updated_at ON conversations;
CREATE TRIGGER update_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger function: when a new message is inserted, "touch" the parent
-- conversation so it floats to the top of the sidebar.
CREATE OR REPLACE FUNCTION touch_conversation_on_message()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
    SET updated_at = NOW()
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

DROP TRIGGER IF EXISTS touch_conversation_on_message_insert ON messages;
CREATE TRIGGER touch_conversation_on_message_insert
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION touch_conversation_on_message();

-- =========================================================================
-- FEEDBACK TABLE
-- Stores thumbs-up / thumbs-down ratings per message per user.
-- UNIQUE(message_id, user_id) enables upsert semantics (toggle feedback).
-- =========================================================================
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL CHECK (feedback_type IN ('thumbs_up', 'thumbs_down')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(message_id, user_id)                -- One rating per user per message
);

CREATE INDEX IF NOT EXISTS idx_feedback_message_id ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);

-- =========================================================================
-- ERRORS TABLE
-- Centralized error log for LLM failures, TTS errors, auth issues, etc.
-- Nullable FK to users/conversations (errors can occur before auth).
-- =========================================================================
CREATE TABLE IF NOT EXISTS errors (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    error_type TEXT NOT NULL,                  -- e.g. 'llm_error', 'tts_error', 'auth_error'
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    request_context JSONB DEFAULT '{}',        -- Truncated request details for debugging
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_errors_user_id ON errors(user_id);
-- Index: aggregate errors by type for monitoring dashboards
CREATE INDEX IF NOT EXISTS idx_errors_error_type ON errors(error_type);
-- Index: recent-first error browsing
CREATE INDEX IF NOT EXISTS idx_errors_created_at ON errors(created_at DESC);

-- =========================================================================
-- TTS EVENTS TABLE
-- Tracks text-to-speech lifecycle events (start, stop, complete, error)
-- for usage analytics and billing.
-- =========================================================================
CREATE TABLE IF NOT EXISTS tts_events (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('start', 'stop', 'complete', 'error')),
    text_length INTEGER,                       -- Character count of text being spoken
    duration_ms INTEGER,                       -- Audio duration if completed
    error_message TEXT,                        -- Error details if event_type is 'error'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tts_events_user_id ON tts_events(user_id);
CREATE INDEX IF NOT EXISTS idx_tts_events_message_id ON tts_events(message_id);
CREATE INDEX IF NOT EXISTS idx_tts_events_created_at ON tts_events(created_at DESC);

-- =========================================================================
-- ANALYTICS EVENTS TABLE
-- Flexible event-sourcing table for client-side analytics: page views,
-- session starts/ends, clicks, referrer tracking, device classification.
-- =========================================================================
CREATE TABLE IF NOT EXISTS analytics_events (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    session_id TEXT NOT NULL,                  -- Client-generated session identifier
    event_type TEXT NOT NULL,                  -- 'page_view', 'session_start', 'session_end', etc.
    event_data JSONB DEFAULT '{}',             -- Flexible payload per event type
    page_path TEXT,
    referrer TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_events_user_id ON analytics_events(user_id);
-- Index: group events by client session
CREATE INDEX IF NOT EXISTS idx_analytics_events_session_id ON analytics_events(session_id);
-- Index: aggregate by event type
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_type ON analytics_events(event_type);
-- Index: recent-first event browsing
CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at DESC);

-- =========================================================================
-- SAFE COLUMN MIGRATIONS (users table additions)
-- Each block is idempotent -- safe to re-run on every deploy.
-- =========================================================================

-- stripe_customer_id: links the user to their Stripe Customer object
-- for payment processing and credit purchases.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'users' AND column_name = 'stripe_customer_id') THEN
        ALTER TABLE users ADD COLUMN stripe_customer_id TEXT;
    END IF;
END $$;

-- denomination: the user's self-identified Jewish denomination
-- (e.g. 'modern_orthodox', 'conservative', 'just_jewish').
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'users' AND column_name = 'denomination') THEN
        ALTER TABLE users ADD COLUMN denomination TEXT DEFAULT 'just_jewish';
    END IF;
END $$;

-- bio: free-text field for the user to describe themselves (max 200 chars
-- enforced at the API layer via Pydantic validation).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'users' AND column_name = 'bio') THEN
        ALTER TABLE users ADD COLUMN bio TEXT;
    END IF;
END $$;

-- =========================================================================
-- PURCHASES TABLE
-- Records every credit purchase. The lifecycle is:
--   pending -> completed (credits added) | failed | refunded
-- Idempotency: complete_purchase() checks status before adding credits.
-- =========================================================================
CREATE TABLE IF NOT EXISTS purchases (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_payment_intent_id TEXT UNIQUE NOT NULL,  -- Unique per Stripe payment
    stripe_customer_id TEXT,
    amount_cents INTEGER NOT NULL,                   -- Price in US cents
    credits_purchased INTEGER NOT NULL,              -- Number of credits bought
    package_id TEXT NOT NULL,                         -- References a package slug
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ                         -- Set when status -> 'completed'
);

CREATE INDEX IF NOT EXISTS idx_purchases_user_id ON purchases(user_id);
-- Index: webhook lookup by Stripe PaymentIntent ID
CREATE INDEX IF NOT EXISTS idx_purchases_stripe_payment_intent_id ON purchases(stripe_payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_purchases_status ON purchases(status);

-- =========================================================================
-- D'VAR TORAH CACHE TABLE
-- Caches AI-generated weekly Torah commentaries keyed by (parsha, year).
-- The 'generating' flag implements optimistic locking so only one
-- serverless instance generates a given entry.
-- =========================================================================
CREATE TABLE IF NOT EXISTS dvar_torah (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    parsha_name TEXT NOT NULL,
    parsha_name_hebrew TEXT,
    hebrew_year INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',               -- The generated commentary
    generating BOOLEAN DEFAULT FALSE,              -- TRUE while generation in progress
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Unique constraint: one cached entry per parsha per Hebrew year
CREATE UNIQUE INDEX IF NOT EXISTS idx_dvar_torah_parsha_year ON dvar_torah(parsha_name, hebrew_year);
"""


async def init_schema():
    """Execute the full DDL schema against the database.

    Uses a PostgreSQL advisory lock (ID 1) in non-blocking mode so that
    if multiple serverless instances cold-start simultaneously, only one
    performs the migration while the others skip gracefully.

    This function is idempotent -- all DDL uses ``IF NOT EXISTS`` and
    safe ``DO $$ ... $$`` blocks for column additions.
    """
    async with get_connection() as conn:
        # Try to acquire advisory lock (non-blocking)
        # Lock ID 1 is reserved for schema initialization
        acquired = await conn.fetchval("SELECT pg_try_advisory_lock(1)")
        if not acquired:
            # Another process is initializing, skip
            return
        try:
            await conn.execute(SCHEMA_SQL)
        finally:
            # Release the advisory lock
            await conn.execute("SELECT pg_advisory_unlock(1)")


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


async def upsert_user(user_id: str, email: str, first_name: str = None, last_name: str = None) -> dict:
    """Create a new user or update an existing one from WorkOS authentication data.

    New users receive 3 starting credits. On conflict (same ``id``), the
    email, name fields, and ``updated_at`` timestamp are refreshed.

    Args:
        user_id: The WorkOS user ID (used as primary key).
        email: The user's email address.
        first_name: Optional first name.
        last_name: Optional last name.

    Returns:
        A dict of the full user row including ``credits`` and timestamps.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (id, email, first_name, last_name, credits)
            VALUES ($1, $2, $3, $4, 3)
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                updated_at = NOW()
            RETURNING id, email, first_name, last_name, credits, created_at, updated_at
            """,
            user_id, email, first_name, last_name
        )
        return dict(row)


async def get_user(user_id: str) -> Optional[dict]:
    """Fetch a user record by their WorkOS ID.

    Args:
        user_id: The WorkOS user ID.

    Returns:
        A dict of the user row, or ``None`` if not found.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, first_name, last_name, credits, created_at, updated_at FROM users WHERE id = $1",
            user_id
        )
        return dict(row) if row else None


async def get_user_credits(user_id: str) -> Optional[int]:
    """Return the number of chat credits remaining for a user.

    Args:
        user_id: The WorkOS user ID.

    Returns:
        The integer credit balance, or ``None`` if the user does not exist.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT credits FROM users WHERE id = $1",
            user_id
        )
        return row['credits'] if row else None


async def consume_credit(user_id: str) -> bool:
    """Atomically decrement one credit from the user's balance.

    The UPDATE uses a ``WHERE credits > 0`` guard so that the operation
    is a no-op (returns ``False``) when the balance is already zero,
    avoiding negative balances without a separate SELECT.

    Args:
        user_id: The WorkOS user ID.

    Returns:
        ``True`` if a credit was consumed, ``False`` if the balance was
        already zero or the user does not exist.
    """
    async with get_connection() as conn:
        result = await conn.fetchrow(
            """
            UPDATE users
            SET credits = credits - 1, updated_at = NOW()
            WHERE id = $1 AND credits > 0
            RETURNING credits
            """,
            user_id
        )
        return result is not None


async def add_credits(user_id: str, amount: int) -> Optional[int]:
    """Add credits to a user's account after a successful purchase.

    Args:
        user_id: The WorkOS user ID.
        amount: Number of credits to add (must be positive).

    Returns:
        The new credit balance after the addition, or ``None`` if the
        user does not exist.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET credits = credits + $2, updated_at = NOW()
            WHERE id = $1
            RETURNING credits
            """,
            user_id, amount
        )
        return row['credits'] if row else None


# ---------------------------------------------------------------------------
# Credit & Purchase Management
# ---------------------------------------------------------------------------


async def get_stripe_customer_id(user_id: str) -> Optional[str]:
    """Look up the Stripe Customer ID associated with a user.

    Args:
        user_id: The WorkOS user ID.

    Returns:
        The Stripe Customer ID string, or ``None`` if not set or user
        does not exist.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id FROM users WHERE id = $1",
            user_id
        )
        return row['stripe_customer_id'] if row else None


async def set_stripe_customer_id(user_id: str, stripe_customer_id: str) -> bool:
    """Persist the Stripe Customer ID on the user record.

    Called once when a Stripe Customer is first created for a user.

    Args:
        user_id: The WorkOS user ID.
        stripe_customer_id: The Stripe ``cus_`` prefixed identifier.

    Returns:
        ``True`` if the update affected exactly one row.
    """
    async with get_connection() as conn:
        result = await conn.execute(
            """
            UPDATE users
            SET stripe_customer_id = $2, updated_at = NOW()
            WHERE id = $1
            """,
            user_id, stripe_customer_id
        )
        return result == "UPDATE 1"


async def get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch a user's profile fields (denomination and bio).

    Args:
        user_id: The WorkOS user ID.

    Returns:
        A dict with ``denomination`` (str) and ``bio`` (str), or ``None``
        if the user does not exist.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT denomination, bio FROM users WHERE id = $1",
            user_id
        )
        if row:
            return {
                "denomination": row['denomination'] or 'just_jewish',
                "bio": row['bio'] or ''
            }
        return None


async def update_user_profile(user_id: str, denomination: str = None, bio: str = None) -> bool:
    """Partially update a user's profile fields.

    Only the provided (non-``None``) fields are updated. Builds a dynamic
    SQL ``SET`` clause to avoid overwriting fields that weren't submitted.

    Args:
        user_id: The WorkOS user ID.
        denomination: New denomination value, or ``None`` to leave unchanged.
        bio: New bio text, or ``None`` to leave unchanged.

    Returns:
        ``True`` if the update affected exactly one row, ``False`` otherwise
        (e.g., no fields provided or user not found).
    """
    async with get_connection() as conn:
        # Build dynamic update query based on what's provided
        updates = []
        params = [user_id]
        param_idx = 2

        if denomination is not None:
            updates.append(f"denomination = ${param_idx}")
            params.append(denomination)
            param_idx += 1

        if bio is not None:
            updates.append(f"bio = ${param_idx}")
            params.append(bio)
            param_idx += 1

        if not updates:
            return False

        query = f"""
            UPDATE users
            SET {', '.join(updates)}, updated_at = NOW()
            WHERE id = $1
        """
        result = await conn.execute(query, *params)
        return result == "UPDATE 1"


async def create_purchase(
    user_id: str,
    stripe_payment_intent_id: str,
    stripe_customer_id: str,
    amount_cents: int,
    credits_purchased: int,
    package_id: str
) -> dict:
    """Insert a new purchase record with ``status='pending'``.

    Called when a Stripe PaymentIntent is created, before the payment
    is confirmed. The record transitions to ``completed`` or ``failed``
    when the Stripe webhook fires.

    Args:
        user_id: The WorkOS user ID making the purchase.
        stripe_payment_intent_id: The Stripe PaymentIntent ID (unique).
        stripe_customer_id: The Stripe Customer ID.
        amount_cents: Purchase price in US cents.
        credits_purchased: Number of credits in the selected package.
        package_id: Identifier for the credit package (e.g., ``"10_credits"``).

    Returns:
        A dict of the newly created purchase row.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO purchases (user_id, stripe_payment_intent_id, stripe_customer_id, amount_cents, credits_purchased, package_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, user_id, stripe_payment_intent_id, amount_cents, credits_purchased, package_id, status, created_at
            """,
            user_id, stripe_payment_intent_id, stripe_customer_id, amount_cents, credits_purchased, package_id
        )
        return dict(row)


async def get_purchase_by_intent_id(stripe_payment_intent_id: str) -> Optional[dict]:
    """Look up a purchase record by its Stripe PaymentIntent ID.

    Args:
        stripe_payment_intent_id: The Stripe ``pi_`` prefixed identifier.

    Returns:
        A dict of the purchase row, or ``None`` if not found.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, stripe_payment_intent_id, amount_cents, credits_purchased, package_id, status, created_at, completed_at
            FROM purchases
            WHERE stripe_payment_intent_id = $1
            """,
            stripe_payment_intent_id
        )
        return dict(row) if row else None


async def complete_purchase(stripe_payment_intent_id: str) -> Optional[dict]:
    """Finalize a purchase: add credits to the user and mark it completed.

    Runs inside a database transaction to ensure atomicity -- either both
    the credit addition and the status update succeed, or neither does.

    Idempotent: if the purchase is already ``completed``, returns it
    without adding credits again (safe for webhook retries).

    Args:
        stripe_payment_intent_id: The Stripe PaymentIntent ID to complete.

    Returns:
        A dict of the updated purchase row, or ``None`` if the
        PaymentIntent was not found.
    """
    async with get_connection() as conn:
        async with conn.transaction():
            # Get the purchase details
            purchase = await conn.fetchrow(
                """
                SELECT id, user_id, credits_purchased, status
                FROM purchases
                WHERE stripe_payment_intent_id = $1
                """,
                stripe_payment_intent_id
            )

            if not purchase:
                return None

            # Check if already completed (idempotency)
            if purchase['status'] == 'completed':
                return dict(await conn.fetchrow(
                    "SELECT * FROM purchases WHERE stripe_payment_intent_id = $1",
                    stripe_payment_intent_id
                ))

            # Add credits to user
            await conn.execute(
                """
                UPDATE users
                SET credits = credits + $2, updated_at = NOW()
                WHERE id = $1
                """,
                purchase['user_id'], purchase['credits_purchased']
            )

            # Mark purchase as completed
            row = await conn.fetchrow(
                """
                UPDATE purchases
                SET status = 'completed', completed_at = NOW()
                WHERE stripe_payment_intent_id = $1
                RETURNING id, user_id, stripe_payment_intent_id, amount_cents, credits_purchased, package_id, status, created_at, completed_at
                """,
                stripe_payment_intent_id
            )
            return dict(row)


async def fail_purchase(stripe_payment_intent_id: str) -> Optional[dict]:
    """Transition a purchase to ``failed`` status.

    Args:
        stripe_payment_intent_id: The Stripe PaymentIntent ID.

    Returns:
        A dict with the purchase summary, or ``None`` if not found.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE purchases
            SET status = 'failed'
            WHERE stripe_payment_intent_id = $1
            RETURNING id, user_id, stripe_payment_intent_id, status
            """,
            stripe_payment_intent_id
        )
        return dict(row) if row else None


async def get_user_purchases(user_id: str, limit: int = 50) -> list[dict]:
    """Retrieve a user's purchase history, most recent first.

    Args:
        user_id: The WorkOS user ID.
        limit: Maximum number of records to return (default 50).

    Returns:
        A list of purchase dicts ordered by ``created_at DESC``.
    """
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id, stripe_payment_intent_id, amount_cents, credits_purchased, package_id, status, created_at, completed_at
            FROM purchases
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Conversation Management
# ---------------------------------------------------------------------------


async def create_conversation(user_id: str, title: str = None) -> dict:
    """Create a new conversation thread for a user.

    Args:
        user_id: The WorkOS user ID who owns the conversation.
        title: Optional title (auto-generated later from the first message
            if not provided).

    Returns:
        A dict of the newly created conversation row.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (user_id, title)
            VALUES ($1, $2)
            RETURNING id, user_id, title, created_at, updated_at
            """,
            user_id, title
        )
        return dict(row)


async def get_conversation(conversation_id: str, user_id: str) -> Optional[dict]:
    """Fetch a conversation by ID, scoped to the owning user.

    Args:
        conversation_id: The conversation UUID.
        user_id: The WorkOS user ID (ownership check).

    Returns:
        A dict of the conversation row, or ``None`` if not found or
        not owned by the given user.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM conversations
            WHERE id = $1 AND user_id = $2
            """,
            conversation_id, user_id
        )
        return dict(row) if row else None


async def list_conversations(user_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """List conversations for a user, ordered by most recently active.

    Includes the first message content as a preview snippet.

    Args:
        user_id: The WorkOS user ID.
        limit: Maximum conversations to return.
        offset: Pagination offset.

    Returns:
        A list of conversation dicts with an additional ``first_message``
        field containing the opening message content.
    """
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.user_id, c.title, c.created_at, c.updated_at,
                   (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY created_at LIMIT 1) as first_message
            FROM conversations c
            WHERE c.user_id = $1
            ORDER BY c.updated_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id, limit, offset
        )
        return [dict(row) for row in rows]


async def update_conversation(conversation_id: str, user_id: str, title: str) -> Optional[dict]:
    """Update a conversation's title (ownership-scoped).

    Args:
        conversation_id: The conversation UUID.
        user_id: The WorkOS user ID (ownership check).
        title: The new title string.

    Returns:
        A dict of the updated conversation row, or ``None`` if not found.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE conversations
            SET title = $3
            WHERE id = $1 AND user_id = $2
            RETURNING id, user_id, title, created_at, updated_at
            """,
            conversation_id, user_id, title
        )
        return dict(row) if row else None


async def delete_conversation(conversation_id: str, user_id: str) -> bool:
    """Delete a conversation and all its messages (via CASCADE).

    Args:
        conversation_id: The conversation UUID.
        user_id: The WorkOS user ID (ownership check).

    Returns:
        ``True`` if a row was deleted, ``False`` if not found.
    """
    async with get_connection() as conn:
        result = await conn.execute(
            "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
            conversation_id, user_id
        )
        return result == "DELETE 1"


# ---------------------------------------------------------------------------
# Message Management
# ---------------------------------------------------------------------------


async def add_message(conversation_id: str, role: str, content: str, metadata: dict = None) -> dict:
    """Insert a new message into a conversation.

    Metadata is serialized to JSON for storage in the JSONB column.
    A trigger automatically updates the parent conversation's
    ``updated_at`` timestamp.

    Args:
        conversation_id: The parent conversation UUID.
        role: Either ``"user"`` or ``"assistant"``.
        content: The message text.
        metadata: Optional dict of pipeline metrics or other data.

    Returns:
        A dict of the newly created message row with ``metadata``
        deserialized back to a Python dict.
    """
    import json
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (conversation_id, role, content, metadata)
            VALUES ($1, $2, $3, $4)
            RETURNING id, conversation_id, role, content, metadata, created_at
            """,
            conversation_id, role, content, json.dumps(metadata or {})
        )
        result = dict(row)
        # Parse metadata back to dict
        if result.get('metadata'):
            result['metadata'] = json.loads(result['metadata']) if isinstance(result['metadata'], str) else result['metadata']
        return result


async def get_messages(conversation_id: str, limit: int = 100) -> list[dict]:
    """Retrieve messages for a conversation in chronological order.

    Args:
        conversation_id: The conversation UUID.
        limit: Maximum number of messages to return (default 100).

    Returns:
        A list of message dicts ordered by ``created_at ASC``, with
        ``metadata`` deserialized from JSON.
    """
    import json
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT id, conversation_id, role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC
            LIMIT $2
            """,
            conversation_id, limit
        )
        messages = []
        for row in rows:
            msg = dict(row)
            if msg.get('metadata'):
                msg['metadata'] = json.loads(msg['metadata']) if isinstance(msg['metadata'], str) else msg['metadata']
            messages.append(msg)
        return messages


async def generate_conversation_title(conversation_id: str) -> Optional[str]:
    """Derive a conversation title from the first user message.

    Takes the first line of the first user message, truncated to 50
    characters, with an ellipsis appended if any content was omitted.

    Args:
        conversation_id: The conversation UUID.

    Returns:
        A title string, or ``None`` if no user messages exist yet.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT content FROM messages
            WHERE conversation_id = $1 AND role = 'user'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            conversation_id
        )
        if row:
            content = row['content']
            # Use the first line, truncated to 50 characters
            first_line = content.split('\n', 1)[0]
            title = first_line[:50]
            # Append ellipsis only if the title omits some of the message
            if len(title) < len(first_line) or '\n' in content:
                title += "..."
            return title
        return None


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


async def upsert_feedback(message_id: str, user_id: str, feedback_type: str) -> dict:
    """Create or update a user's feedback rating for a message.

    Uses ``ON CONFLICT (message_id, user_id) DO UPDATE`` for upsert
    semantics -- submitting a new rating replaces the previous one.

    Args:
        message_id: The message UUID being rated.
        user_id: The WorkOS user ID providing the rating.
        feedback_type: Either ``"thumbs_up"`` or ``"thumbs_down"``.

    Returns:
        A dict of the upserted feedback row.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO feedback (message_id, user_id, feedback_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (message_id, user_id) DO UPDATE SET
                feedback_type = EXCLUDED.feedback_type,
                created_at = NOW()
            RETURNING id, message_id, user_id, feedback_type, created_at
            """,
            message_id, user_id, feedback_type
        )
        return dict(row)


async def delete_feedback(message_id: str, user_id: str) -> bool:
    """Remove a user's feedback rating for a message.

    Args:
        message_id: The message UUID.
        user_id: The WorkOS user ID.

    Returns:
        ``True`` if a feedback row was deleted, ``False`` if none existed.
    """
    async with get_connection() as conn:
        result = await conn.execute(
            "DELETE FROM feedback WHERE message_id = $1 AND user_id = $2",
            message_id, user_id
        )
        return result == "DELETE 1"


async def get_message_feedback(message_id: str, user_id: str) -> Optional[dict]:
    """Retrieve the feedback a specific user gave for a specific message.

    Args:
        message_id: The message UUID.
        user_id: The WorkOS user ID.

    Returns:
        A dict of the feedback row, or ``None`` if no feedback exists.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, message_id, user_id, feedback_type, created_at
            FROM feedback
            WHERE message_id = $1 AND user_id = $2
            """,
            message_id, user_id
        )
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Error Logging
# ---------------------------------------------------------------------------


async def log_error(
    error_type: str,
    error_message: str,
    user_id: str = None,
    conversation_id: str = None,
    stack_trace: str = None,
    request_context: dict = None
) -> dict:
    """Persist an application error to the errors table for monitoring.

    Args:
        error_type: Category string (e.g., ``"llm_error"``, ``"tts_error"``).
        error_message: Human-readable error description.
        user_id: Optional WorkOS user ID if the error is user-scoped.
        conversation_id: Optional conversation UUID for context.
        stack_trace: Optional Python traceback string.
        request_context: Optional dict of request details (truncated
            to avoid storing sensitive data).

    Returns:
        A dict of the newly created error row.
    """
    import json
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO errors (user_id, conversation_id, error_type, error_message, stack_trace, request_context)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, user_id, conversation_id, error_type, error_message, created_at
            """,
            user_id, conversation_id, error_type, error_message, stack_trace,
            json.dumps(request_context or {})
        )
        return dict(row)


async def get_error_stats(days: int = 7) -> list[dict]:
    """Aggregate error counts by type and day for the last N days.

    Args:
        days: Look-back window in days (clamped to 1-365).

    Returns:
        A list of dicts with ``error_type``, ``count``, and ``day`` fields,
        ordered by day descending then count descending.
    """
    # Validate days parameter
    days = max(1, min(days, 365))
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT error_type, COUNT(*) as count,
                   DATE_TRUNC('day', created_at) as day
            FROM errors
            WHERE created_at > NOW() - INTERVAL '1 day' * $1
            GROUP BY error_type, DATE_TRUNC('day', created_at)
            ORDER BY day DESC, count DESC
            """,
            days
        )
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# TTS Events
# ---------------------------------------------------------------------------


async def log_tts_event(
    user_id: str,
    event_type: str,
    message_id: str = None,
    text_length: int = None,
    duration_ms: int = None,
    error_message: str = None
) -> dict:
    """Record a text-to-speech lifecycle event.

    Args:
        user_id: The WorkOS user ID.
        event_type: One of ``"start"``, ``"stop"``, ``"complete"``, ``"error"``.
        message_id: Optional message UUID being spoken.
        text_length: Character count of the text being spoken.
        duration_ms: Audio playback duration (for ``"complete"`` events).
        error_message: Error description (for ``"error"`` events).

    Returns:
        A dict of the newly created TTS event row.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tts_events (user_id, message_id, event_type, text_length, duration_ms, error_message)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, user_id, message_id, event_type, text_length, duration_ms, created_at
            """,
            user_id, message_id, event_type, text_length, duration_ms, error_message
        )
        return dict(row)


async def get_tts_stats(days: int = 7) -> dict:
    """Compute aggregate TTS usage statistics for the last N days.

    Args:
        days: Look-back window in days (clamped to 1-365).

    Returns:
        A dict with keys: ``total_starts``, ``total_completes``,
        ``total_stops``, ``total_errors``, ``avg_duration_ms``,
        ``total_chars_spoken``.
    """
    # Validate days parameter
    days = max(1, min(days, 365))
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'start') as total_starts,
                COUNT(*) FILTER (WHERE event_type = 'complete') as total_completes,
                COUNT(*) FILTER (WHERE event_type = 'stop') as total_stops,
                COUNT(*) FILTER (WHERE event_type = 'error') as total_errors,
                AVG(duration_ms) FILTER (WHERE event_type = 'complete') as avg_duration_ms,
                SUM(text_length) FILTER (WHERE event_type = 'start') as total_chars_spoken
            FROM tts_events
            WHERE created_at > NOW() - INTERVAL '1 day' * $1
            """,
            days
        )
        return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


async def log_analytics_event(
    session_id: str,
    event_type: str,
    user_id: str = None,
    event_data: dict = None,
    page_path: str = None,
    referrer: str = None,
    user_agent: str = None
) -> dict:
    """Insert a client-side analytics event into the database.

    Args:
        session_id: Client-generated session identifier.
        event_type: Event category (e.g., ``"page_view"``, ``"session_start"``).
        user_id: Optional WorkOS user ID (``None`` for anonymous visitors).
        event_data: Flexible JSON payload for the event type.
        page_path: The URL path the event occurred on.
        referrer: The HTTP referrer URL.
        user_agent: The client's User-Agent header.

    Returns:
        A dict of the newly created analytics event row.
    """
    import json
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO analytics_events (user_id, session_id, event_type, event_data, page_path, referrer, user_agent)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, session_id, event_type, page_path, created_at
            """,
            user_id, session_id, event_type, json.dumps(event_data or {}),
            page_path, referrer, user_agent
        )
        return dict(row)


async def get_session_stats(days: int = 7) -> dict:
    """Compute aggregate session statistics for the last N days.

    Args:
        days: Look-back window in days (clamped to 1-365).

    Returns:
        A dict with ``unique_sessions``, ``total_page_views``, and
        ``unique_users``.
    """
    # Validate days parameter
    days = max(1, min(days, 365))
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(DISTINCT session_id) as unique_sessions,
                COUNT(*) FILTER (WHERE event_type = 'page_view') as total_page_views,
                COUNT(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL) as unique_users
            FROM analytics_events
            WHERE created_at > NOW() - INTERVAL '1 day' * $1
            """,
            days
        )
        return dict(row) if row else {}


async def get_referrer_stats(days: int = 7) -> list[dict]:
    """Rank traffic sources by unique sessions for the last N days.

    Args:
        days: Look-back window in days (clamped to 1-365).

    Returns:
        A list of dicts with ``referrer`` and ``sessions`` fields, top 20,
        ordered by session count descending.
    """
    # Validate days parameter
    days = max(1, min(days, 365))
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT
                COALESCE(referrer, 'direct') as referrer,
                COUNT(DISTINCT session_id) as sessions
            FROM analytics_events
            WHERE event_type = 'session_start'
              AND created_at > NOW() - INTERVAL '1 day' * $1
            GROUP BY referrer
            ORDER BY sessions DESC
            LIMIT 20
            """,
            days
        )
        return [dict(row) for row in rows]


async def get_device_stats(days: int = 7) -> list[dict]:
    """Classify sessions by device type (mobile, tablet, desktop).

    Device classification is based on simple User-Agent substring matching.

    Args:
        days: Look-back window in days (clamped to 1-365).

    Returns:
        A list of dicts with ``device_type`` and ``sessions`` fields.
    """
    # Validate days parameter
    days = max(1, min(days, 365))
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT
                CASE
                    WHEN user_agent ILIKE '%%mobile%%' OR user_agent ILIKE '%%android%%' OR user_agent ILIKE '%%iphone%%' THEN 'mobile'
                    WHEN user_agent ILIKE '%%tablet%%' OR user_agent ILIKE '%%ipad%%' THEN 'tablet'
                    ELSE 'desktop'
                END as device_type,
                COUNT(DISTINCT session_id) as sessions
            FROM analytics_events
            WHERE event_type = 'session_start'
              AND created_at > NOW() - INTERVAL '1 day' * $1
            GROUP BY device_type
            ORDER BY sessions DESC
            """,
            days
        )
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# D'var Torah Cache
# ---------------------------------------------------------------------------


async def get_dvar_torah(parsha_name: str, hebrew_year: int) -> Optional[dict]:
    """Retrieve a cached d'var Torah by parsha name and Hebrew year.

    Args:
        parsha_name: English transliterated parsha name.
        hebrew_year: The Hebrew calendar year (e.g., 5786).

    Returns:
        A dict of the cached entry including ``content`` and ``generating``
        flag, or ``None`` if no entry exists for this parsha/year.
    """
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, parsha_name, parsha_name_hebrew, hebrew_year, content, generating, metadata, created_at
            FROM dvar_torah
            WHERE parsha_name = $1 AND hebrew_year = $2
            """,
            parsha_name, hebrew_year
        )
        return dict(row) if row else None


async def claim_dvar_torah_generation(parsha_name: str, parsha_name_hebrew: str, hebrew_year: int) -> Optional[str]:
    """Atomically claim a d'var Torah generation slot using INSERT ... ON CONFLICT DO NOTHING.

    This implements optimistic locking: the first caller to insert wins
    and receives the new row's ID; subsequent callers for the same
    (parsha, year) get ``None`` and should wait for the winner to finish.

    Args:
        parsha_name: English transliterated parsha name.
        parsha_name_hebrew: Hebrew parsha name.
        hebrew_year: The Hebrew calendar year.

    Returns:
        The UUID of the newly created row if this caller claimed the
        generation slot, or ``None`` if another instance already claimed it.
    """
    async with get_connection() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO dvar_torah (parsha_name, parsha_name_hebrew, hebrew_year, generating)
                VALUES ($1, $2, $3, TRUE)
                ON CONFLICT (parsha_name, hebrew_year) DO NOTHING
                RETURNING id
                """,
                parsha_name, parsha_name_hebrew, hebrew_year
            )
            return row['id'] if row else None
        except Exception:
            return None


async def complete_dvar_torah_generation(row_id: str, content: str, metadata: dict = None) -> bool:
    """Save the generated d'var Torah content and clear the generating flag.

    Args:
        row_id: The UUID returned by ``claim_dvar_torah_generation``.
        content: The full generated commentary text.
        metadata: Optional dict of generation metadata (model, tokens, etc.).

    Returns:
        ``True`` if the row was updated, ``False`` if the row_id was
        not found.
    """
    import json
    async with get_connection() as conn:
        result = await conn.execute(
            """
            UPDATE dvar_torah
            SET content = $2, generating = FALSE, metadata = $3
            WHERE id = $1
            """,
            row_id, content, json.dumps(metadata or {})
        )
        return result == "UPDATE 1"


async def fail_dvar_torah_generation(row_id: str) -> bool:
    """Clean up a failed d'var Torah generation by deleting the placeholder row.

    Only deletes rows still in the ``generating=TRUE`` state to avoid
    accidentally removing a successfully completed entry.

    Args:
        row_id: The UUID returned by ``claim_dvar_torah_generation``.

    Returns:
        ``True`` if the placeholder row was deleted, ``False`` if not
        found or already completed.
    """
    async with get_connection() as conn:
        result = await conn.execute(
            "DELETE FROM dvar_torah WHERE id = $1 AND generating = TRUE",
            row_id
        )
        return result == "DELETE 1"

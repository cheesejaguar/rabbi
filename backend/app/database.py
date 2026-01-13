"""Database connection and schema management for Vercel Postgres (Neon)."""

import asyncio
import asyncpg
from typing import Optional
from contextlib import asynccontextmanager

from .config import get_settings

# Global connection pool with lock to prevent race conditions
_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
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

            # Parse the URL and add SSL requirement for Neon
            db_url = settings.db_url
            if "sslmode" not in db_url:
                db_url = f"{db_url}?sslmode=require" if "?" not in db_url else f"{db_url}&sslmode=require"

            _pool = await asyncpg.create_pool(
                db_url,
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
        return _pool


async def close_pool():
    """Close the database connection pool."""
    global _pool
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None


@asynccontextmanager
async def get_connection():
    """Get a database connection from the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


# SQL Schema
SCHEMA_SQL = """
-- Users table (synced from WorkOS)
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,  -- WorkOS user ID
    email TEXT UNIQUE NOT NULL,
    first_name TEXT,
    last_name TEXT,
    credits INTEGER DEFAULT 3,  -- Starting credits for new users
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add credits column if it doesn't exist (for existing databases)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'users' AND column_name = 'credits') THEN
        ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 3;
    END IF;
END $$;

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_conversations_updated_at ON conversations;
CREATE TRIGGER update_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to update conversation updated_at when a message is added
CREATE OR REPLACE FUNCTION touch_conversation_on_message()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
    SET updated_at = NOW()
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

-- Trigger to update conversation updated_at on new messages
DROP TRIGGER IF EXISTS touch_conversation_on_message_insert ON messages;
CREATE TRIGGER touch_conversation_on_message_insert
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION touch_conversation_on_message();

-- Feedback table for thumbs up/down
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL CHECK (feedback_type IN ('thumbs_up', 'thumbs_down')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(message_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_message_id ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);

-- Errors table for tracking failures and API errors
CREATE TABLE IF NOT EXISTS errors (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    error_type TEXT NOT NULL,  -- 'llm_error', 'tts_error', 'auth_error', 'validation_error', etc.
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    request_context JSONB DEFAULT '{}',  -- Request details for debugging
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_errors_user_id ON errors(user_id);
CREATE INDEX IF NOT EXISTS idx_errors_error_type ON errors(error_type);
CREATE INDEX IF NOT EXISTS idx_errors_created_at ON errors(created_at DESC);

-- TTS events table for tracking speak button usage
CREATE TABLE IF NOT EXISTS tts_events (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('start', 'stop', 'complete', 'error')),
    text_length INTEGER,  -- Character count of text being spoken
    duration_ms INTEGER,  -- Audio duration if completed
    error_message TEXT,   -- Error details if event_type is 'error'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tts_events_user_id ON tts_events(user_id);
CREATE INDEX IF NOT EXISTS idx_tts_events_message_id ON tts_events(message_id);
CREATE INDEX IF NOT EXISTS idx_tts_events_created_at ON tts_events(created_at DESC);

-- Analytics events table for flexible event tracking
-- Tracks sessions, page views, referrers, device info, etc.
CREATE TABLE IF NOT EXISTS analytics_events (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    session_id TEXT NOT NULL,  -- Client-generated session identifier
    event_type TEXT NOT NULL,  -- 'page_view', 'session_start', 'session_end', 'click', etc.
    event_data JSONB DEFAULT '{}',  -- Flexible data for different event types
    page_path TEXT,
    referrer TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_events_user_id ON analytics_events(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_session_id ON analytics_events(session_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_type ON analytics_events(event_type);
CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at DESC);
"""


async def init_schema():
    """Initialize the database schema.

    Uses PostgreSQL advisory locks to prevent concurrent schema initialization
    from multiple serverless function instances.
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


# User operations
async def upsert_user(user_id: str, email: str, first_name: str = None, last_name: str = None) -> dict:
    """Create or update a user from WorkOS data."""
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
    """Get a user by ID."""
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, first_name, last_name, credits, created_at, updated_at FROM users WHERE id = $1",
            user_id
        )
        return dict(row) if row else None


async def get_user_credits(user_id: str) -> Optional[int]:
    """Get a user's remaining credits."""
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT credits FROM users WHERE id = $1",
            user_id
        )
        return row['credits'] if row else None


async def consume_credit(user_id: str) -> bool:
    """Consume one credit from user. Returns True if successful, False if no credits."""
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
    """Add credits to a user's account. Returns new balance."""
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


# Conversation operations
async def create_conversation(user_id: str, title: str = None) -> dict:
    """Create a new conversation."""
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
    """Get a conversation by ID (only if owned by user)."""
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
    """List conversations for a user, most recent first."""
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
    """Update a conversation's title."""
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
    """Delete a conversation (cascade deletes messages)."""
    async with get_connection() as conn:
        result = await conn.execute(
            "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
            conversation_id, user_id
        )
        return result == "DELETE 1"


# Message operations
async def add_message(conversation_id: str, role: str, content: str, metadata: dict = None) -> dict:
    """Add a message to a conversation."""
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
    """Get messages for a conversation, oldest first."""
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
    """Generate a title from the first user message (truncated)."""
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


# Feedback operations
async def upsert_feedback(message_id: str, user_id: str, feedback_type: str) -> dict:
    """Create or update feedback for a message."""
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
    """Remove feedback for a message."""
    async with get_connection() as conn:
        result = await conn.execute(
            "DELETE FROM feedback WHERE message_id = $1 AND user_id = $2",
            message_id, user_id
        )
        return result == "DELETE 1"


async def get_message_feedback(message_id: str, user_id: str) -> Optional[dict]:
    """Get feedback for a specific message by user."""
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


# Error logging operations
async def log_error(
    error_type: str,
    error_message: str,
    user_id: str = None,
    conversation_id: str = None,
    stack_trace: str = None,
    request_context: dict = None
) -> dict:
    """Log an error to the database."""
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
    """Get error statistics for the last N days."""
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


# TTS event operations
async def log_tts_event(
    user_id: str,
    event_type: str,
    message_id: str = None,
    text_length: int = None,
    duration_ms: int = None,
    error_message: str = None
) -> dict:
    """Log a TTS event (start, stop, complete, error)."""
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
    """Get TTS usage statistics for the last N days."""
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


# Analytics event operations
async def log_analytics_event(
    session_id: str,
    event_type: str,
    user_id: str = None,
    event_data: dict = None,
    page_path: str = None,
    referrer: str = None,
    user_agent: str = None
) -> dict:
    """Log an analytics event."""
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
    """Get session statistics for the last N days."""
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
    """Get referrer statistics for the last N days."""
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
    """Get device/browser statistics for the last N days."""
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

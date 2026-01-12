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
"""


async def init_schema():
    """Initialize the database schema."""
    async with get_connection() as conn:
        await conn.execute(SCHEMA_SQL)


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

"""Tests for database.py - Database operations."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import json


class TestDatabasePool:
    """Test database connection pool management."""

    @pytest.fixture(autouse=True)
    def reset_pool(self):
        """Reset the global pool before each test."""
        import asyncio
        import app.database as db
        db._pool = None
        # Reset the lock to avoid issues between tests
        db._pool_lock = asyncio.Lock()
        yield
        db._pool = None
        db._pool_lock = asyncio.Lock()

    @pytest.mark.asyncio
    async def test_get_pool_creates_pool(self):
        """Test that get_pool creates a connection pool."""
        mock_pool = AsyncMock()

        with patch('app.database.get_settings') as mock_settings:
            mock_settings.return_value.db_url = "postgresql://user:pass@host/db"

            with patch('app.database.asyncpg.create_pool', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_pool

                from app.database import get_pool
                pool = await get_pool()

                assert pool == mock_pool
                mock_create.assert_called_once()
                # Verify SSL mode is added
                call_args = mock_create.call_args
                assert "sslmode=require" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_pool_reuses_existing_pool(self):
        """Test that get_pool reuses existing pool."""
        mock_pool = AsyncMock()

        with patch('app.database.get_settings') as mock_settings:
            mock_settings.return_value.db_url = "postgresql://user:pass@host/db"

            with patch('app.database.asyncpg.create_pool', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_pool

                from app.database import get_pool
                pool1 = await get_pool()
                pool2 = await get_pool()

                assert pool1 is pool2
                # Should only be called once
                assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_get_pool_raises_without_db_url(self):
        """Test that get_pool raises error when DB URL not configured."""
        with patch('app.database.get_settings') as mock_settings:
            mock_settings.return_value.db_url = ""

            from app.database import get_pool
            with pytest.raises(RuntimeError, match="Database URL not configured"):
                await get_pool()

    @pytest.mark.asyncio
    async def test_close_pool(self):
        """Test that close_pool closes the pool."""
        import app.database as db
        mock_pool = AsyncMock()
        db._pool = mock_pool

        await db.close_pool()

        mock_pool.close.assert_called_once()
        assert db._pool is None

    @pytest.mark.asyncio
    async def test_close_pool_when_none(self):
        """Test that close_pool handles None pool gracefully."""
        import app.database as db
        db._pool = None

        # Should not raise
        await db.close_pool()
        assert db._pool is None


class TestGetConnection:
    """Test get_connection context manager."""

    @pytest.mark.asyncio
    async def test_get_connection_yields_connection(self):
        """Test that get_connection yields a connection from pool."""
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

        with patch('app.database.get_pool', new_callable=AsyncMock) as mock_get_pool:
            mock_get_pool.return_value = mock_pool

            from app.database import get_connection
            async with get_connection() as conn:
                assert conn == mock_conn


class TestUserOperations:
    """Test user database operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = AsyncMock()
        return conn

    @pytest.mark.asyncio
    async def test_upsert_user_creates_new_user(self, mock_connection):
        """Test upserting a new user."""
        mock_row = {
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import upsert_user
            result = await upsert_user("user-123", "test@example.com", "Test", "User")

            assert result["id"] == "user-123"
            assert result["email"] == "test@example.com"
            mock_connection.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_returns_user(self, mock_connection):
        """Test getting an existing user."""
        mock_row = {
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_user
            result = await get_user("user-123")

            assert result["id"] == "user-123"

    @pytest.mark.asyncio
    async def test_get_user_returns_none_for_missing(self, mock_connection):
        """Test getting a non-existent user."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_user
            result = await get_user("nonexistent")

            assert result is None


class TestConversationOperations:
    """Test conversation database operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_create_conversation(self, mock_connection):
        """Test creating a new conversation."""
        mock_row = {
            "id": "conv-123",
            "user_id": "user-123",
            "title": "Test Conversation",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import create_conversation
            result = await create_conversation("user-123", "Test Conversation")

            assert result["id"] == "conv-123"
            assert result["user_id"] == "user-123"
            assert result["title"] == "Test Conversation"

    @pytest.mark.asyncio
    async def test_get_conversation(self, mock_connection):
        """Test getting a conversation by ID."""
        mock_row = {
            "id": "conv-123",
            "user_id": "user-123",
            "title": "Test",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_conversation
            result = await get_conversation("conv-123", "user-123")

            assert result["id"] == "conv-123"

    @pytest.mark.asyncio
    async def test_get_conversation_returns_none_for_wrong_user(self, mock_connection):
        """Test that get_conversation returns None for wrong user."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_conversation
            result = await get_conversation("conv-123", "wrong-user")

            assert result is None

    @pytest.mark.asyncio
    async def test_list_conversations(self, mock_connection):
        """Test listing conversations for a user."""
        mock_rows = [
            {"id": "conv-1", "user_id": "user-123", "title": "First", "created_at": "2024-01-01", "updated_at": "2024-01-01", "first_message": "Hello"},
            {"id": "conv-2", "user_id": "user-123", "title": "Second", "created_at": "2024-01-02", "updated_at": "2024-01-02", "first_message": "Hi"},
        ]
        mock_connection.fetch = AsyncMock(return_value=mock_rows)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import list_conversations
            result = await list_conversations("user-123")

            assert len(result) == 2
            assert result[0]["id"] == "conv-1"
            assert result[1]["id"] == "conv-2"

    @pytest.mark.asyncio
    async def test_list_conversations_with_pagination(self, mock_connection):
        """Test listing conversations with limit and offset."""
        mock_rows = [{"id": "conv-3", "user_id": "user-123", "title": "Third", "created_at": "2024-01-03", "updated_at": "2024-01-03", "first_message": None}]
        mock_connection.fetch = AsyncMock(return_value=mock_rows)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import list_conversations
            result = await list_conversations("user-123", limit=10, offset=2)

            assert len(result) == 1
            # Verify pagination parameters were passed
            call_args = mock_connection.fetch.call_args
            assert 10 in call_args[0]  # limit
            assert 2 in call_args[0]   # offset

    @pytest.mark.asyncio
    async def test_update_conversation(self, mock_connection):
        """Test updating a conversation title."""
        mock_row = {
            "id": "conv-123",
            "user_id": "user-123",
            "title": "Updated Title",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import update_conversation
            result = await update_conversation("conv-123", "user-123", "Updated Title")

            assert result["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_delete_conversation(self, mock_connection):
        """Test deleting a conversation."""
        mock_connection.execute = AsyncMock(return_value="DELETE 1")

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import delete_conversation
            result = await delete_conversation("conv-123", "user-123")

            assert result is True

    @pytest.mark.asyncio
    async def test_delete_conversation_not_found(self, mock_connection):
        """Test deleting a non-existent conversation."""
        mock_connection.execute = AsyncMock(return_value="DELETE 0")

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import delete_conversation
            result = await delete_conversation("nonexistent", "user-123")

            assert result is False


class TestMessageOperations:
    """Test message database operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_add_message(self, mock_connection):
        """Test adding a message to a conversation."""
        mock_row = {
            "id": "msg-123",
            "conversation_id": "conv-123",
            "role": "user",
            "content": "Hello!",
            "metadata": "{}",
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import add_message
            result = await add_message("conv-123", "user", "Hello!")

            assert result["id"] == "msg-123"
            assert result["role"] == "user"
            assert result["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_add_message_with_metadata(self, mock_connection):
        """Test adding a message with metadata."""
        metadata = {"key": "value"}
        mock_row = {
            "id": "msg-123",
            "conversation_id": "conv-123",
            "role": "assistant",
            "content": "Response",
            "metadata": json.dumps(metadata),
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import add_message
            result = await add_message("conv-123", "assistant", "Response", metadata)

            assert result["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_get_messages(self, mock_connection):
        """Test getting messages for a conversation."""
        mock_rows = [
            {"id": "msg-1", "conversation_id": "conv-123", "role": "user", "content": "Hello", "metadata": "{}", "created_at": "2024-01-01T00:00:00Z"},
            {"id": "msg-2", "conversation_id": "conv-123", "role": "assistant", "content": "Hi there!", "metadata": "{}", "created_at": "2024-01-01T00:00:01Z"},
        ]
        mock_connection.fetch = AsyncMock(return_value=mock_rows)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_messages
            result = await get_messages("conv-123")

            assert len(result) == 2
            assert result[0]["role"] == "user"
            assert result[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_generate_conversation_title(self, mock_connection):
        """Test generating a title from first user message (short, single line)."""
        mock_row = {"content": "What is the meaning of Shabbat?"}
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import generate_conversation_title
            result = await generate_conversation_title("conv-123")

            # Short single-line content should not have ellipsis
            assert result == "What is the meaning of Shabbat?"
            assert not result.endswith("...")

    @pytest.mark.asyncio
    async def test_generate_conversation_title_truncates_long_content(self, mock_connection):
        """Test that long messages are truncated for titles."""
        long_content = "A" * 100  # 100 characters on single line
        mock_row = {"content": long_content}
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import generate_conversation_title
            result = await generate_conversation_title("conv-123")

            assert len(result) == 53  # 50 chars + "..."
            assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_generate_conversation_title_multiline_adds_ellipsis(self, mock_connection):
        """Test that multiline content adds ellipsis even if first line is short."""
        multiline_content = "Short first line\nSecond line with more content"
        mock_row = {"content": multiline_content}
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import generate_conversation_title
            result = await generate_conversation_title("conv-123")

            assert result == "Short first line..."

    @pytest.mark.asyncio
    async def test_generate_conversation_title_short_single_line_no_ellipsis(self, mock_connection):
        """Test that short single-line content has no ellipsis."""
        short_content = "Short question"
        mock_row = {"content": short_content}
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import generate_conversation_title
            result = await generate_conversation_title("conv-123")

            assert result == "Short question"
            assert not result.endswith("...")

    @pytest.mark.asyncio
    async def test_generate_conversation_title_no_messages(self, mock_connection):
        """Test title generation when no messages exist."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import generate_conversation_title
            result = await generate_conversation_title("conv-123")

            assert result is None


class TestInitSchema:
    """Test schema initialization."""

    @pytest.mark.asyncio
    async def test_init_schema_executes_sql(self):
        """Test that init_schema executes the schema SQL with advisory lock."""
        mock_connection = AsyncMock()
        # Mock advisory lock acquisition (returns True = lock acquired)
        mock_connection.fetchval = AsyncMock(return_value=True)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import init_schema, SCHEMA_SQL
            await init_schema()

            # Should acquire lock, execute schema, then release lock
            mock_connection.fetchval.assert_called_once_with("SELECT pg_try_advisory_lock(1)")
            assert mock_connection.execute.call_count == 2
            mock_connection.execute.assert_any_call(SCHEMA_SQL)
            mock_connection.execute.assert_any_call("SELECT pg_advisory_unlock(1)")

    @pytest.mark.asyncio
    async def test_init_schema_skips_when_lock_not_acquired(self):
        """Test that init_schema skips execution when advisory lock is not acquired."""
        mock_connection = AsyncMock()
        # Mock advisory lock acquisition failure (returns False)
        mock_connection.fetchval = AsyncMock(return_value=False)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import init_schema
            await init_schema()

            # Should only try to acquire lock, then skip
            mock_connection.fetchval.assert_called_once()
            mock_connection.execute.assert_not_called()


class TestStripeCustomerOperations:
    """Test Stripe customer database operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_get_stripe_customer_id_returns_id(self, mock_connection):
        """Test getting existing Stripe customer ID."""
        mock_row = {"stripe_customer_id": "cus_test123"}
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_stripe_customer_id
            result = await get_stripe_customer_id("user-123")

            assert result == "cus_test123"

    @pytest.mark.asyncio
    async def test_get_stripe_customer_id_returns_none(self, mock_connection):
        """Test getting non-existent Stripe customer ID."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_stripe_customer_id
            result = await get_stripe_customer_id("user-123")

            assert result is None

    @pytest.mark.asyncio
    async def test_set_stripe_customer_id(self, mock_connection):
        """Test setting Stripe customer ID for user."""
        mock_connection.execute = AsyncMock(return_value="UPDATE 1")

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import set_stripe_customer_id
            result = await set_stripe_customer_id("user-123", "cus_new123")

            assert result is True
            mock_connection.execute.assert_called_once()


class TestPurchaseOperations:
    """Test purchase database operations."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_create_purchase(self, mock_connection):
        """Test creating a new purchase record."""
        mock_row = {
            "id": "purchase-123",
            "user_id": "user-123",
            "stripe_payment_intent_id": "pi_test123",
            "stripe_customer_id": "cus_test123",
            "amount_cents": 100,
            "credits_purchased": 10,
            "package_id": "credits_10",
            "status": "pending",
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import create_purchase
            result = await create_purchase(
                user_id="user-123",
                stripe_payment_intent_id="pi_test123",
                stripe_customer_id="cus_test123",
                amount_cents=100,
                credits_purchased=10,
                package_id="credits_10",
            )

            assert result["id"] == "purchase-123"
            assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_purchase_by_intent_id(self, mock_connection):
        """Test getting purchase by payment intent ID."""
        mock_row = {
            "id": "purchase-123",
            "user_id": "user-123",
            "stripe_payment_intent_id": "pi_test123",
            "status": "pending",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_purchase_by_intent_id
            result = await get_purchase_by_intent_id("pi_test123")

            assert result["stripe_payment_intent_id"] == "pi_test123"

    @pytest.mark.asyncio
    async def test_get_purchase_by_intent_id_not_found(self, mock_connection):
        """Test getting non-existent purchase."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import get_purchase_by_intent_id
            result = await get_purchase_by_intent_id("pi_nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_complete_purchase_adds_credits(self, mock_connection):
        """Test completing a purchase adds credits to user."""
        # First fetchrow returns the pending purchase
        pending_purchase = {
            "id": "purchase-123",
            "user_id": "user-123",
            "credits_purchased": 10,
            "status": "pending",
        }
        # Second fetchrow returns the completed purchase (after UPDATE RETURNING)
        completed_purchase = {
            "id": "purchase-123",
            "user_id": "user-123",
            "credits_purchased": 10,
            "status": "completed",
        }
        mock_connection.fetchrow = AsyncMock(side_effect=[pending_purchase, completed_purchase])
        mock_connection.execute = AsyncMock()

        # Mock the transaction context manager
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        mock_connection.transaction = MagicMock(return_value=mock_transaction)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import complete_purchase
            result = await complete_purchase("pi_test123")

            assert result["status"] == "completed"
            assert result["credits_purchased"] == 10
            # Should have called execute to add credits
            assert mock_connection.execute.called

    @pytest.mark.asyncio
    async def test_complete_purchase_idempotent(self, mock_connection):
        """Test that completing already-completed purchase is idempotent."""
        # First fetchrow returns already completed purchase
        already_completed_check = {
            "id": "purchase-123",
            "user_id": "user-123",
            "credits_purchased": 10,
            "status": "completed",
        }
        # Second fetchrow returns full purchase for idempotent return
        already_completed_full = {
            "id": "purchase-123",
            "user_id": "user-123",
            "credits_purchased": 10,
            "status": "completed",
            "stripe_payment_intent_id": "pi_test123",
        }
        mock_connection.fetchrow = AsyncMock(side_effect=[already_completed_check, already_completed_full])

        # Mock the transaction context manager
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        mock_connection.transaction = MagicMock(return_value=mock_transaction)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import complete_purchase
            result = await complete_purchase("pi_test123")

            # Should return the purchase without modifying anything
            assert result["status"] == "completed"
            # execute should not be called for already completed purchase
            mock_connection.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_purchase_not_found(self, mock_connection):
        """Test completing non-existent purchase."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        # Mock the transaction context manager
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        mock_connection.transaction = MagicMock(return_value=mock_transaction)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import complete_purchase
            result = await complete_purchase("pi_nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_fail_purchase(self, mock_connection):
        """Test marking a purchase as failed."""
        mock_row = {
            "id": "purchase-123",
            "user_id": "user-123",
            "status": "failed",
        }
        mock_connection.fetchrow = AsyncMock(return_value=mock_row)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import fail_purchase
            result = await fail_purchase("pi_test123")

            assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_fail_purchase_not_found(self, mock_connection):
        """Test failing non-existent purchase."""
        mock_connection.fetchrow = AsyncMock(return_value=None)

        with patch('app.database.get_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_connection)
            mock_ctx.return_value.__aexit__ = AsyncMock()

            from app.database import fail_purchase
            result = await fail_purchase("pi_nonexistent")

            assert result is None

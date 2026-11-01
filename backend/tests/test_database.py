"""Tests for database.py - Database operations.

Every test runs the real SQL against a throwaway PostgreSQL server (the
``real_db`` fixture in conftest.py), so they check what the queries actually
store and return rather than which SQL strings were sent to a mock.
"""

import asyncio
import uuid

import asyncpg
import pytest


async def _make_user(db, user_id="user-123", email=None, **kw):
    return await db.upsert_user(user_id, email or f"{user_id}@example.com", **kw)


class TestDatabasePool:
    """Test database connection pool management."""

    async def test_get_pool_creates_pool(self, real_db):
        """get_pool creates a working pool whose connections decode JSONB as dicts."""
        pool = await real_db.get_pool()

        assert isinstance(pool, asyncpg.Pool)
        async with pool.acquire() as conn:
            # The JSONB codec registered by _init_connection round-trips dicts.
            assert await conn.fetchval("SELECT $1::jsonb", {"a": 1}) == {"a": 1}

    async def test_get_pool_adds_sslmode_require(self, real_db, monkeypatch):
        """Hosted URLs without an sslmode get sslmode=require appended."""
        from app.config import get_settings

        seen = {}

        async def fake_create_pool(url, **kwargs):
            seen["url"] = url
            seen["init"] = kwargs.get("init")
            return object()

        monkeypatch.setattr(get_settings(), "database_url", "postgresql://user:pass@host/db")
        monkeypatch.setattr(real_db.asyncpg, "create_pool", fake_create_pool)
        real_db._pool = None

        await real_db.get_pool()
        real_db._pool = None  # not a real pool; keep teardown's close_pool a no-op

        assert seen["url"] == "postgresql://user:pass@host/db?sslmode=require"
        assert seen["init"] is real_db._init_connection

    async def test_get_pool_reuses_existing_pool(self, real_db):
        """get_pool returns the same pool on every call."""
        pool1 = await real_db.get_pool()
        pool2 = await real_db.get_pool()

        assert pool1 is pool2

    async def test_get_pool_concurrent_callers_share_one_pool(self, real_db):
        """Concurrent cold-start callers get a single pool, not one each."""
        await real_db.close_pool()
        pools = await asyncio.gather(*(real_db.get_pool() for _ in range(5)))

        assert all(p is pools[0] for p in pools)

    async def test_get_pool_raises_without_db_url(self, real_db, monkeypatch):
        """get_pool raises when no database URL is configured."""
        from app.config import get_settings

        await real_db.close_pool()
        monkeypatch.setattr(get_settings(), "database_url", "")
        monkeypatch.setattr(get_settings(), "postgres_url", "")

        with pytest.raises(RuntimeError, match="Database URL not configured"):
            await real_db.get_pool()

    async def test_close_pool(self, real_db):
        """close_pool closes the pool and clears the global."""
        pool = await real_db.get_pool()

        await real_db.close_pool()

        assert pool._closed
        assert real_db._pool is None

    async def test_close_pool_when_none(self, real_db):
        """close_pool is a no-op when no pool exists."""
        await real_db.close_pool()
        await real_db.close_pool()
        assert real_db._pool is None


class TestGetConnection:
    """Test get_connection context manager."""

    async def test_get_connection_yields_connection(self, real_db):
        """get_connection yields a live connection from the pool."""
        async with real_db.get_connection() as conn:
            assert isinstance(conn, asyncpg.Connection)
            assert await conn.fetchval("SELECT 41 + 1") == 42


class TestUserOperations:
    """Test user database operations."""

    async def test_upsert_user_creates_new_user(self, real_db):
        """A new user is created with the signup credit grant."""
        from app.config import get_settings

        user = await real_db.upsert_user("user-123", "test@example.com", "Test", "User")

        assert user["id"] == "user-123"
        assert user["email"] == "test@example.com"
        assert user["first_name"] == "Test"
        assert user["last_name"] == "User"
        assert user["credits"] == get_settings().signup_credits
        assert user["is_admin"] is False

    async def test_upsert_user_updates_existing_without_regranting_credits(self, real_db):
        """Re-login refreshes profile fields but keeps the spent credit balance."""
        await real_db.upsert_user("user-123", "old@example.com", "Old", "Name")
        assert await real_db.consume_credit("user-123") is True
        balance = await real_db.get_user_credits("user-123")

        user = await real_db.upsert_user("user-123", "new@example.com", "New", "Name")

        assert user["email"] == "new@example.com"
        assert user["first_name"] == "New"
        assert user["credits"] == balance

    async def test_upsert_user_promotes_admin_email(self, real_db):
        """Emails in ADMIN_EMAILS (case-insensitive) become admins."""
        from app.config import get_settings

        admin_email = get_settings().admin_email_list[0]
        user = await real_db.upsert_user("admin-1", admin_email.upper())

        assert user["is_admin"] is True
        assert await real_db.is_user_admin("admin-1") is True

    async def test_get_user_returns_user(self, real_db):
        """get_user returns the stored row."""
        await real_db.upsert_user("user-123", "test@example.com", "Test", "User")

        user = await real_db.get_user("user-123")

        assert user["id"] == "user-123"
        assert user["email"] == "test@example.com"
        assert user["first_name"] == "Test"

    async def test_get_user_returns_none_for_missing(self, real_db):
        """get_user returns None for an unknown id."""
        assert await real_db.get_user("nonexistent") is None

    async def test_consume_credit_stops_at_zero(self, real_db):
        """consume_credit decrements and refuses once the balance is zero."""
        await _make_user(real_db)
        await real_db.add_credits("user-123", -(await real_db.get_user_credits("user-123")) + 1)

        assert await real_db.consume_credit("user-123") is True
        assert await real_db.get_user_credits("user-123") == 0
        assert await real_db.consume_credit("user-123") is False
        assert await real_db.get_user_credits("user-123") == 0
        assert await real_db.consume_credit("missing") is False

    async def test_add_credits_returns_new_balance(self, real_db):
        """add_credits returns the new balance, or None for an unknown user."""
        user = await _make_user(real_db)

        assert await real_db.add_credits("user-123", 25) == user["credits"] + 25
        assert await real_db.add_credits("missing", 5) is None

    async def test_update_user_profile_denomination_only(self, real_db):
        """Updating only denomination leaves bio unchanged."""
        await _make_user(real_db)
        await real_db.update_user_profile("user-123", bio="Existing bio")

        assert await real_db.update_user_profile("user-123", denomination="conservative") is True

        assert await real_db.get_user_profile("user-123") == {
            "denomination": "conservative", "bio": "Existing bio",
        }

    async def test_update_user_profile_bio_only(self, real_db):
        """Updating only bio leaves denomination unchanged."""
        await _make_user(real_db)
        await real_db.update_user_profile("user-123", denomination="reform")

        assert await real_db.update_user_profile("user-123", bio="Hello world") is True

        assert await real_db.get_user_profile("user-123") == {"denomination": "reform", "bio": "Hello world"}

    async def test_update_user_profile_both_fields(self, real_db):
        """Both fields can be updated in one call."""
        await _make_user(real_db)

        assert await real_db.update_user_profile("user-123", denomination="reform", bio="My bio") is True

        assert await real_db.get_user_profile("user-123") == {"denomination": "reform", "bio": "My bio"}

    async def test_get_user_profile_defaults(self, real_db):
        """A fresh user's profile falls back to just_jewish and an empty bio."""
        await _make_user(real_db)

        assert await real_db.get_user_profile("user-123") == {"denomination": "just_jewish", "bio": ""}
        assert await real_db.get_user_profile("missing") is None

    async def test_update_user_profile_no_fields_returns_false(self, real_db):
        """Providing neither field is a no-op returning False."""
        await _make_user(real_db)

        assert await real_db.update_user_profile("user-123") is False

    async def test_update_user_profile_no_matching_row(self, real_db):
        """A non-existent user results in False."""
        assert await real_db.update_user_profile("missing-user", denomination="reform") is False


class TestConversationOperations:
    """Test conversation database operations."""

    async def test_create_conversation(self, real_db):
        """A conversation is created for the user with the given title."""
        await _make_user(real_db)

        conv = await real_db.create_conversation("user-123", "Test Title")

        assert uuid.UUID(conv["id"])  # text column holding a generated UUID
        assert conv["user_id"] == "user-123"
        assert conv["title"] == "Test Title"

    async def test_get_conversation(self, real_db):
        """get_conversation returns the owner's conversation."""
        await _make_user(real_db)
        conv = await real_db.create_conversation("user-123", "Test")

        result = await real_db.get_conversation(conv["id"], "user-123")

        assert result["id"] == conv["id"]
        assert result["title"] == "Test"

    async def test_get_conversation_returns_none_for_wrong_user(self, real_db):
        """Another user cannot read the conversation."""
        await _make_user(real_db)
        await _make_user(real_db, "other-user")
        conv = await real_db.create_conversation("user-123", "Private")

        assert await real_db.get_conversation(conv["id"], "other-user") is None

    async def test_list_conversations(self, real_db):
        """Only the user's conversations are listed, most recently active first,
        with the first message as a preview."""
        await _make_user(real_db)
        await _make_user(real_db, "other-user")
        older = await real_db.create_conversation("user-123", "Older")
        newer = await real_db.create_conversation("user-123", "Newer")
        await real_db.create_conversation("other-user", "Not mine")
        await real_db.add_message(older["id"], "user", "first question")
        await real_db.add_message(older["id"], "assistant", "an answer")

        result = await real_db.list_conversations("user-123")

        # Adding messages bumps the conversation's updated_at via trigger.
        assert [c["title"] for c in result] == ["Older", "Newer"]
        assert result[0]["first_message"] == "first question"
        assert result[1]["first_message"] is None
        assert {c["id"] for c in result} == {older["id"], newer["id"]}

    async def test_list_conversations_with_pagination(self, real_db):
        """limit and offset page through the list."""
        await _make_user(real_db)
        for i in range(5):
            await real_db.create_conversation("user-123", f"Conv {i}")

        page1 = await real_db.list_conversations("user-123", limit=2, offset=0)
        page2 = await real_db.list_conversations("user-123", limit=2, offset=2)
        page3 = await real_db.list_conversations("user-123", limit=2, offset=4)

        assert len(page1) == 2 and len(page2) == 2 and len(page3) == 1
        titles = [c["title"] for c in page1 + page2 + page3]
        assert sorted(titles) == [f"Conv {i}" for i in range(5)]

    async def test_update_conversation(self, real_db):
        """The owner can rename; another user cannot."""
        await _make_user(real_db)
        await _make_user(real_db, "other-user")
        conv = await real_db.create_conversation("user-123", "Old")

        assert await real_db.update_conversation(conv["id"], "other-user", "Hijack") is None
        result = await real_db.update_conversation(conv["id"], "user-123", "New Title")

        assert result["title"] == "New Title"
        assert (await real_db.get_conversation(conv["id"], "user-123"))["title"] == "New Title"

    async def test_delete_conversation(self, real_db):
        """Deleting removes the conversation and its messages."""
        await _make_user(real_db)
        conv = await real_db.create_conversation("user-123")
        await real_db.add_message(conv["id"], "user", "hello")

        assert await real_db.delete_conversation(conv["id"], "user-123") is True

        assert await real_db.get_conversation(conv["id"], "user-123") is None
        assert await real_db.get_messages(conv["id"]) == []

    async def test_delete_conversation_not_found(self, real_db):
        """Deleting an unknown or another user's conversation returns False."""
        await _make_user(real_db)
        await _make_user(real_db, "other-user")
        conv = await real_db.create_conversation("user-123")

        assert await real_db.delete_conversation(str(uuid.uuid4()), "user-123") is False
        assert await real_db.delete_conversation(conv["id"], "other-user") is False
        assert await real_db.get_conversation(conv["id"], "user-123") is not None


class TestMessageOperations:
    """Test message database operations."""

    @pytest.fixture
    async def conv(self, real_db):
        await _make_user(real_db)
        return await real_db.create_conversation("user-123")

    async def test_add_message(self, real_db, conv):
        """A message is stored with an empty metadata dict by default."""
        msg = await real_db.add_message(conv["id"], "user", "Hello")

        assert msg["conversation_id"] == conv["id"]
        assert msg["role"] == "user"
        assert msg["content"] == "Hello"
        assert msg["metadata"] == {}

    async def test_add_message_with_metadata(self, real_db, conv):
        """Metadata round-trips through JSONB as a dict (not a JSON string)."""
        metadata = {"pastoral_mode": "teaching", "cost": 0.0012, "flags": ["a", "b"]}

        msg = await real_db.add_message(conv["id"], "assistant", "Response", metadata)

        assert msg["metadata"] == metadata
        stored = await real_db.get_messages(conv["id"])
        assert stored[0]["metadata"] == metadata

    async def test_get_messages(self, real_db, conv):
        """Messages come back in chronological order, honoring limit."""
        await real_db.add_message(conv["id"], "user", "Q1")
        await real_db.add_message(conv["id"], "assistant", "A1")
        await real_db.add_message(conv["id"], "user", "Q2")

        result = await real_db.get_messages(conv["id"])
        limited = await real_db.get_messages(conv["id"], limit=2)

        assert [(m["role"], m["content"]) for m in result] == [
            ("user", "Q1"), ("assistant", "A1"), ("user", "Q2"),
        ]
        assert [m["content"] for m in limited] == ["Q1", "A1"]

    async def test_generate_conversation_title(self, real_db, conv):
        """The title is the first *user* message; short single lines get no ellipsis."""
        await real_db.add_message(conv["id"], "assistant", "Shalom! How can I help?")
        await real_db.add_message(conv["id"], "user", "What is the meaning of Shabbat?")
        await real_db.add_message(conv["id"], "user", "A later question")

        assert await real_db.generate_conversation_title(conv["id"]) == "What is the meaning of Shabbat?"

    async def test_generate_conversation_title_truncates_long_content(self, real_db, conv):
        """Long single-line messages are cut to 50 chars plus an ellipsis."""
        await real_db.add_message(conv["id"], "user", "A" * 100)

        assert await real_db.generate_conversation_title(conv["id"]) == "A" * 50 + "..."

    async def test_generate_conversation_title_multiline_adds_ellipsis(self, real_db, conv):
        """Multiline content adds an ellipsis even if the first line is short."""
        await real_db.add_message(conv["id"], "user", "Short first line\nSecond line with more content")

        assert await real_db.generate_conversation_title(conv["id"]) == "Short first line..."

    async def test_generate_conversation_title_no_messages(self, real_db, conv):
        """No user messages means no title."""
        assert await real_db.generate_conversation_title(conv["id"]) is None
        await real_db.add_message(conv["id"], "assistant", "Only the rebbe spoke")
        assert await real_db.generate_conversation_title(conv["id"]) is None


class TestInitSchema:
    """Test schema initialization."""

    async def test_init_schema_executes_sql(self, real_db, pg_url):
        """init_schema creates the tables, is idempotent, and releases its advisory lock."""
        await real_db.init_schema()  # second run (fixture ran it once)

        async with real_db.get_connection() as conn:
            tables = {r["tablename"] for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )}
        assert {"users", "conversations", "messages", "purchases", "credit_ledger"} <= tables

        # The lock was released: another session can take it.
        other = await asyncpg.connect(pg_url)
        try:
            assert await other.fetchval("SELECT pg_try_advisory_lock(1)") is True
            await other.execute("SELECT pg_advisory_unlock(1)")
        finally:
            await other.close()

    async def test_init_schema_skips_when_lock_not_acquired(self, real_db, pg_url):
        """While another session holds the lock, init_schema does nothing."""
        holder = await asyncpg.connect(pg_url)
        try:
            assert await holder.fetchval("SELECT pg_try_advisory_lock(1)") is True
            # Drop a table the schema would recreate; a skipped init leaves it missing.
            async with real_db.get_connection() as conn:
                await conn.execute("DROP TABLE safety_events")

            await real_db.init_schema()

            async with real_db.get_connection() as conn:
                assert await conn.fetchval("SELECT to_regclass('public.safety_events')") is None
        finally:
            await holder.execute("SELECT pg_advisory_unlock(1)")
            await holder.close()

        await real_db.init_schema()
        async with real_db.get_connection() as conn:
            assert await conn.fetchval("SELECT to_regclass('public.safety_events')") is not None


class TestStripeCustomerOperations:
    """Test Stripe customer database operations."""

    async def test_get_stripe_customer_id_returns_id(self, real_db):
        """A stored Stripe customer id is returned."""
        await _make_user(real_db)
        assert await real_db.set_stripe_customer_id("user-123", "cus_test123") is True

        assert await real_db.get_stripe_customer_id("user-123") == "cus_test123"

    async def test_get_stripe_customer_id_returns_none(self, real_db):
        """None for a user without one, and for an unknown user."""
        await _make_user(real_db)

        assert await real_db.get_stripe_customer_id("user-123") is None
        assert await real_db.get_stripe_customer_id("missing") is None

    async def test_set_stripe_customer_id(self, real_db):
        """Setting the id for an unknown user returns False."""
        assert await real_db.set_stripe_customer_id("missing", "cus_x") is False


class TestPurchaseOperations:
    """Test purchase database operations."""

    @pytest.fixture
    async def user(self, real_db):
        return await _make_user(real_db)

    async def _purchase(self, db, intent="pi_test123", credits=10):
        return await db.create_purchase("user-123", intent, "cus_test", 500, credits, "10_credits")

    async def test_create_purchase(self, real_db, user):
        """A new purchase starts pending with the given details."""
        purchase = await self._purchase(real_db)

        assert purchase["user_id"] == "user-123"
        assert purchase["stripe_payment_intent_id"] == "pi_test123"
        assert purchase["amount_cents"] == 500
        assert purchase["credits_purchased"] == 10
        assert purchase["package_id"] == "10_credits"
        assert purchase["status"] == "pending"

    async def test_get_purchase_by_intent_id(self, real_db, user):
        """A purchase can be looked up by PaymentIntent id."""
        created = await self._purchase(real_db)

        purchase = await real_db.get_purchase_by_intent_id("pi_test123")

        assert purchase["id"] == created["id"]
        assert purchase["status"] == "pending"
        assert purchase["completed_at"] is None

    async def test_get_purchase_by_intent_id_not_found(self, real_db):
        """Unknown PaymentIntent ids return None."""
        assert await real_db.get_purchase_by_intent_id("pi_nonexistent") is None

    async def test_complete_purchase_adds_credits(self, real_db, user):
        """Completing a purchase credits the user, writes the ledger, and marks it completed."""
        await self._purchase(real_db, credits=10)

        result = await real_db.complete_purchase("pi_test123")

        assert result["status"] == "completed"
        assert result["completed_at"] is not None
        assert await real_db.get_user_credits("user-123") == user["credits"] + 10
        async with real_db.get_connection() as conn:
            ledger = await conn.fetch("SELECT delta, reason, ref FROM credit_ledger WHERE user_id = 'user-123'")
        assert [tuple(r) for r in ledger] == [(10, "purchase", "pi_test123")]

    async def test_complete_purchase_idempotent(self, real_db, user):
        """A retried webhook does not add credits twice."""
        await self._purchase(real_db, credits=10)
        await real_db.complete_purchase("pi_test123")

        result = await real_db.complete_purchase("pi_test123")

        assert result["status"] == "completed"
        assert await real_db.get_user_credits("user-123") == user["credits"] + 10

    async def test_complete_purchase_not_found(self, real_db, user):
        """Completing an unknown purchase returns None and changes nothing."""
        assert await real_db.complete_purchase("pi_nonexistent") is None
        assert await real_db.get_user_credits("user-123") == user["credits"]

    async def test_fail_purchase(self, real_db, user):
        """A failed purchase is marked failed and grants no credits."""
        await self._purchase(real_db)

        result = await real_db.fail_purchase("pi_test123")

        assert result["status"] == "failed"
        assert (await real_db.get_purchase_by_intent_id("pi_test123"))["status"] == "failed"
        assert await real_db.get_user_credits("user-123") == user["credits"]

    async def test_fail_purchase_not_found(self, real_db):
        """Failing an unknown purchase returns None."""
        assert await real_db.fail_purchase("pi_nonexistent") is None

    async def test_get_user_purchases_newest_first(self, real_db, user):
        """Purchase history is the user's own, most recent first."""
        await self._purchase(real_db, "pi_first")
        await self._purchase(real_db, "pi_second")

        history = await real_db.get_user_purchases("user-123")

        assert [p["stripe_payment_intent_id"] for p in history] == ["pi_second", "pi_first"]
        assert await real_db.get_user_purchases("someone-else") == []

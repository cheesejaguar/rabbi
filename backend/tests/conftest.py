"""Pytest configuration and fixtures."""

import os

import pytest
from unittest.mock import MagicMock

# app.main builds an OpenAI-compatible client at import time, which refuses to
# construct without a key. Tests never reach the real provider; a dummy key
# lets the app import without patching the client class.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")


@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI client for OpenRouter."""
    client = MagicMock()
    # Set up the chat.completions.create method
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock()
    return client


# Alias for backward compatibility with existing tests
@pytest.fixture
def mock_anthropic_client(mock_openai_client):
    """Alias for mock_openai_client for backward compatibility."""
    return mock_openai_client


@pytest.fixture
def mock_claude_response():
    """Create a mock OpenAI-compatible API response with usage metrics."""
    def _create_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
        response = MagicMock()
        choice = MagicMock()
        message = MagicMock()
        message.content = text
        choice.message = message
        response.choices = [choice]
        # Add usage metrics for cost calculation
        usage = MagicMock()
        usage.prompt_tokens = input_tokens
        usage.completion_tokens = output_tokens
        response.usage = usage
        return response
    return _create_response


@pytest.fixture
def sample_conversation_history():
    """Sample conversation history for testing."""
    return [
        {"role": "user", "content": "Hello, I have a question."},
        {"role": "assistant", "content": "Shalom! I'm here to help."},
    ]


# Sandboxed environments ship a preinstalled Chromium whose build number may
# not match the installed Playwright package. Point pytest-playwright at it
# when present so the browser suites run without `playwright install`.
_PREINSTALLED_CHROMIUM = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="session")
def browser_type_launch_args(pytestconfig):
    import os

    args = {}
    if os.path.exists(_PREINSTALLED_CHROMIUM):
        args["executable_path"] = _PREINSTALLED_CHROMIUM
    headed = pytestconfig.getoption("--headed", default=False)
    if headed:
        args["headless"] = False
    return args


# ---------------------------------------------------------------------------
# Real PostgreSQL for database-backed tests
# ---------------------------------------------------------------------------
# The app's SQL is PostgreSQL-specific (JSONB, advisory locks, ON CONFLICT),
# so tests run it against a real throwaway server from ``pgserver`` (a dev
# dependency that bundles the Postgres binaries) instead of mocking asyncpg.


async def _truncate_all(url: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(url)
    try:
        tables = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        if tables:
            names = ", ".join(f'"{t["tablename"]}"' for t in tables)
            await conn.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    """URL of a session-wide PostgreSQL server with the app schema applied."""
    import pgserver

    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    url = server.get_uri()
    # Local unix socket: opt out of the sslmode=require that get_pool adds.
    url = f"{url}{'&' if '?' in url else '?'}sslmode=disable"
    yield url
    server.cleanup()


def _point_app_at(url, monkeypatch):
    import asyncio
    import app.database as db
    from app.config import get_settings

    import sys

    # Modules keep their own ``settings = get_settings()`` reference, which can
    # differ from the cached instance if a test cleared the cache.
    targets = {id(get_settings()): get_settings()}
    for name, mod in list(sys.modules.items()):
        if name == "app" or name.startswith("app."):
            for attr in ("settings", "_settings"):
                obj = getattr(mod, attr, None)
                if obj is not None and hasattr(obj, "database_url"):
                    targets[id(obj)] = obj
    for obj in targets.values():
        monkeypatch.setattr(obj, "database_url", url)
    db._pool = None
    db._pool_lock = asyncio.Lock()


@pytest.fixture
async def real_db(pg_url, monkeypatch):
    """Point app.database at the real test server, with empty tables.

    For async tests that call ``app.database`` directly (same event loop).
    """
    import app.database as db

    _point_app_at(pg_url, monkeypatch)
    await db.init_schema()
    await _truncate_all(pg_url)
    yield db
    await db.close_pool()


@pytest.fixture
def live_db(pg_url, monkeypatch):
    """Same as ``real_db`` for sync ``TestClient`` tests.

    The pool binds to the event loop that first uses it, so use the client as
    a context manager (``with TestClient(app) as client``) to keep one loop for
    the whole test; seed data with ``client.portal.call(db.fn, ...)``.
    """
    import asyncio
    import app.database as db

    _point_app_at(pg_url, monkeypatch)

    async def _prepare():
        await db.init_schema()
        await db.close_pool()
        await _truncate_all(pg_url)

    asyncio.run(_prepare())
    db._pool = None
    db._pool_lock = asyncio.Lock()
    yield db
    db._pool = None
    db._pool_lock = asyncio.Lock()

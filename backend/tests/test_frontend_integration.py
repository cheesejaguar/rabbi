"""Chromium checks driven against the real FastAPI application.

Every other browser test in this suite serves ``frontend/`` from a static file
server and answers the API with ``page.route`` fixtures. That is fast and
hermetic, but it means the browser never touches FastAPI: routing, the auth
middleware, the ``/static`` mount, and the actual response headers are all
stubbed out, so a drift between the synthetic fixtures and the real
application would leave the suite green.

This module closes that gap. It boots the application itself -- with only the
language-model orchestrator mocked, exactly as ``test_public_pages`` does --
under a uvicorn server on an ephemeral port, and drives a real browser at it.
Only ``js.stripe.com`` stays stubbed, because reaching a payment provider from
a test is neither hermetic nor free.

No production data, payment provider, authentication provider, or
language-model call is involved.
"""

import socket
import sys
import threading
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest


pytestmark = pytest.mark.browser

AUTH_USER = {
    "id": "user-integration",
    "email": "integration@example.test",
    "first_name": "Integration",
    "last_name": "Tester",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def live_app():
    """Serve the real application over HTTP for the duration of the module.

    Yields ``(base_url, state)``. Mutating ``state["user"]`` switches the
    request between anonymous and signed-in, which is what distinguishes the
    public landing page from the app shell at ``/``.
    """

    import uvicorn

    orchestrator = Mock()
    orchestrator.get_greeting = AsyncMock(return_value="Shalom, how can I help?")
    orchestrator.ensure_rag = Mock()

    # patch.dict snapshots sys.modules and restores the originals on teardown,
    # so importing a freshly-configured app here does not leak into other test
    # modules that import app.main themselves.
    with patch.dict(sys.modules, {}):
        for name in [key for key in sys.modules if key.startswith("app")]:
            del sys.modules[name]

        with patch("app.agents.orchestrator.OpenAI"):
            with patch("app.agents.RabbiOrchestrator", return_value=orchestrator):
                from app.main import app

                state = {"user": None}

                # The middleware and the route handlers each resolve the caller
                # independently, so both lookups have to answer from state.
                with patch("app.main.get_current_user", side_effect=lambda _request: state["user"]):
                    port = _free_port()
                    config = uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port=port,
                        log_level="warning",
                        lifespan="off",  # no database in this environment
                    )
                    server = uvicorn.Server(config)
                    thread = threading.Thread(target=server.run, daemon=True)
                    thread.start()

                    deadline = time.time() + 30
                    while not server.started and time.time() < deadline:
                        time.sleep(0.05)
                    assert server.started, "uvicorn did not start in time"

                    try:
                        yield f"http://127.0.0.1:{port}", state
                    finally:
                        server.should_exit = True
                        thread.join(timeout=10)


def test_anonymous_visitor_gets_the_landing_page_with_working_assets(page, live_app):
    """The public entry point, served and rendered end to end.

    A stubbed file server cannot catch a stylesheet that 404s behind the
    /static mount, a font the app never exposes, or an auth middleware that
    redirects a page it was supposed to leave public.
    """

    base_url, state = live_app
    state["user"] = None

    failed = []
    console_errors = []
    page.on("requestfailed", lambda request: failed.append(request.url))
    page.on(
        "response",
        lambda response: failed.append(f"{response.status} {response.url}")
        if response.status >= 400
        else None,
    )
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )

    page.set_viewport_size({"width": 1280, "height": 900})
    response = page.goto(f"{base_url}/", wait_until="networkidle")

    assert response.status == 200
    assert page.get_by_role(
        "heading", name="Thoughtful Jewish guidance, grounded in sources."
    ).is_visible()
    # The app shell must not leak to anonymous visitors.
    assert page.locator("#welcomeScreen").count() == 0

    # Every stylesheet the page linked actually parsed, which only holds if
    # the /static mount resolved it.
    loaded_sheets = page.evaluate(
        """
        () => Array.from(document.styleSheets)
          .filter((sheet) => sheet.href)
          .map((sheet) => ({
            href: sheet.href.split('/').pop(),
            rules: (() => { try { return sheet.cssRules.length; } catch (error) { return -1; } })(),
          }))
        """
    )
    assert loaded_sheets, "the landing page linked no external stylesheets"
    for sheet in loaded_sheets:
        assert sheet["rules"] > 0, f"stylesheet served but empty or unparsed: {sheet}"

    assert page.evaluate("document.fonts.size > 0"), "no @font-face rule reached the browser"
    assert failed == [], f"requests failed against the live app: {failed}"
    assert console_errors == []


def test_signed_in_visitor_gets_the_app_shell_from_the_same_route(page, live_app):
    base_url, state = live_app
    state["user"] = AUTH_USER

    page.set_viewport_size({"width": 1280, "height": 900})
    response = page.goto(f"{base_url}/", wait_until="domcontentloaded")

    assert response.status == 200
    assert page.locator("#welcomeScreen").count() == 1
    assert page.locator("#purchaseModal").get_attribute("aria-modal") == "true"


def test_public_routes_answer_get_and_head_with_real_headers(page, live_app):
    """Crawler-facing behavior, checked against the routes as deployed.

    FastAPI's @app.get registers GET alone, so these four answered 405 to the
    HEAD probes crawlers and uptime monitors send before fetching.
    """

    base_url, state = live_app
    state["user"] = None
    request = page.request

    privacy = request.get(f"{base_url}/privacy")
    assert privacy.status == 200
    assert privacy.headers["content-type"].startswith("text/html")
    assert "Privacy Policy | rebbe.dev" in privacy.text()

    robots = request.get(f"{base_url}/robots.txt")
    assert robots.status == 200
    assert "Disallow: /api/" in robots.text()

    sitemap = request.get(f"{base_url}/sitemap.xml")
    assert sitemap.status == 200
    assert "<loc>https://rebbe.dev/privacy</loc>" in sitemap.text()

    for path in ("/", "/privacy", "/robots.txt", "/sitemap.xml"):
        head = request.head(f"{base_url}{path}")
        assert head.status == 200, f"HEAD {path} returned {head.status}"


def test_privacy_policy_renders_for_an_anonymous_browser(page, live_app):
    base_url, state = live_app
    state["user"] = None

    console_errors = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )

    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{base_url}/privacy", wait_until="networkidle")

    assert response.status == 200
    assert page.locator("link[rel='canonical']").get_attribute("href") == (
        "https://rebbe.dev/privacy"
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert console_errors == []


def test_static_assets_are_served_with_usable_content_types(live_app, page):
    """The rebrand added a self-hosted font, icon, and image tree.

    Chromium refuses a font served as text/html and cannot decode an image
    served as the wrong type, so a mount that returns 200 is not on its own
    evidence that the asset works.
    """

    base_url, _state = live_app
    request = page.request

    expectations = {
        "/static/brand.css": "text/css",
        "/static/theme.js": "javascript",
        "/static/app.js": "javascript",
        "/static/admin.js": "javascript",
        "/static/assets/fonts/HankenGrotesk-Variable.ttf": "font",
        "/static/assets/fonts/NotoSansHebrew-Variable.ttf": "font",
        "/static/assets/icons/sun.svg": "image/svg",
        "/static/assets/brand/braided-r.svg": "image/svg",
        "/static/assets/images/braid-macro.avif": "image/avif",
        "/static/assets/images/braid-macro.jpg": "image/jpeg",
        "/static/assets/images/source-sheets.avif": "image/avif",
        "/static/assets/images/social-card.png": "image/png",
    }

    for path, expected_type in expectations.items():
        response = request.get(f"{base_url}{path}")
        assert response.status == 200, f"{path} returned {response.status}"
        content_type = response.headers.get("content-type", "")
        assert expected_type in content_type, (
            f"{path} served as {content_type!r}, expected {expected_type!r}"
        )
        assert len(response.body()) > 0, f"{path} served an empty body"


def test_auth_middleware_still_guards_private_surfaces(live_app, page):
    """A redesign that touched the public-path list must not have widened it."""

    base_url, state = live_app
    state["user"] = None
    request = page.request

    api = request.get(f"{base_url}/api/conversations")
    assert api.status == 401

    admin_api = request.get(f"{base_url}/api/admin/overview")
    assert admin_api.status == 401

    admin_page = request.get(f"{base_url}/admin", max_redirects=0)
    assert admin_page.status == 302
    assert "/auth/logged-out" in admin_page.headers["location"]

"""Dev-only Chromium checks for the redesigned frontend surfaces.

The browser receives synthetic API fixtures. No production data, payment
provider, authentication provider, or language-model call is involved.
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import time
from urllib.parse import urlparse

import pytest


pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


class FrontendHandler(SimpleHTTPRequestHandler):
    """Serve frontend files while preserving the production /static prefix.

    ``stream_plan`` scripts a real, incrementally flushed SSE response for
    POST /api/chat/stream: a list of ``(delay_seconds, event)`` pairs. Tests
    that need tokens to arrive over time (stop, safety-card ordering, block
    stability) let that request through to this server instead of fulfilling
    it in one piece from ``page.route``.
    """

    stream_plan: list = []
    stream_requests: list = []

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat/stream":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            FrontendHandler.stream_requests.append(json.loads(body or b"{}"))
        except ValueError:
            FrontendHandler.stream_requests.append({})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for delay, event in list(FrontendHandler.stream_plan):
                if delay:
                    time.sleep(delay)
                frame = event if isinstance(event, str) else f"data: {json.dumps(event)}\n\n"
                self.wfile.write(frame.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # The client aborted (Stop). That is the behavior under test.
            return

    def do_GET(self):
        request_path = urlparse(self.path).path
        if request_path in {"/privacy", "/privacy/"}:
            self.path = "/privacy.html"
        elif request_path in {"/terms", "/terms/"}:
            self.path = "/terms.html"
        elif self.path == "/static":
            self.path = "/"
        elif self.path.startswith("/static/"):
            self.path = self.path[len("/static"):]
        super().do_GET()

    def log_message(self, _format, *args):
        return


@pytest.fixture(scope="session")
def frontend_url():
    handler = partial(FrontendHandler, directory=str(FRONTEND))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def open_frontend(page, frontend_url: str, filename: str, viewport: dict[str, int]):
    page.set_viewport_size(viewport)
    page.goto(f"{frontend_url}/{filename}", wait_until="domcontentloaded")


def install_stripe_stub(page):
    """Keep modal tests local while exercising the production payment UI.

    The stub records the appearance each Elements group is created with and
    every appearance later pushed through update(), so a test can assert that
    the card form follows a theme change instead of staying on the theme it
    happened to mount under.
    """

    page.add_init_script(
        """
        window.__stripeAppearances = { created: [], updated: [] };
        window.Stripe = () => ({
          elements: (options) => {
            window.__stripeAppearances.created.push(options && options.appearance);
            return {
              create: () => ({
                mount: () => {},
                on: (name, callback) => {
                  if (name === 'ready') queueMicrotask(callback);
                },
                destroy: () => {},
              }),
              update: (options) => {
                window.__stripeAppearances.updated.push(options && options.appearance);
              },
            };
          },
          confirmPayment: async () => ({ paymentIntent: { status: 'succeeded', id: 'pi_synthetic' } }),
        });
        """
    )


def sse(events) -> str:
    """Frame a list of event dicts as an SSE body."""

    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


PACKAGES = {
    "packages": {
        "credits_55": {"credits": 55, "price_cents": 200, "display_price": "$2.00", "label": "Starter"},
        "credits_160": {
            "credits": 160,
            "price_cents": 500,
            "display_price": "$5.00",
            "label": "Standard",
            "recommended": True,
        },
        "credits_400": {"credits": 400, "price_cents": 1200, "display_price": "$12.00", "label": "Plus"},
    }
}


def install_app_routes(
    page,
    *,
    stream_body: str | None = None,
    stream_bodies: list | None = None,
    live_stream: bool = False,
    credits: int = 12,
    conversation_messages: dict | None = None,
    initial_conversations: list | None = None,
):
    """Install a complete, synthetic signed-in session for the app shell.

    Returns a dict that records chat request bodies (``chat_requests``) and
    every other API call (``calls``) so tests can assert on the contract.
    ``stream_bodies`` answers successive chat requests in order; an entry of
    ``None`` aborts that request at the network layer. ``live_stream`` hands
    the chat request to the scripted streaming server (see FrontendHandler).
    """

    conversations = list(initial_conversations or [])
    record = {"chat_requests": [], "calls": []}
    queue = list(stream_bodies or [])
    profile = {
        "denomination": "just_jewish",
        "bio": "Learning one practice at a time.",
    }

    page.route(
        "**/auth/check",
        lambda route: route.fulfill(
            json={
                "authenticated": True,
                "user": {
                    "id": "user-synthetic",
                    "first_name": "Aaron",
                    "last_name": "Example",
                    "email": "aaron@example.test",
                    "is_admin": False,
                },
            }
        ),
    )

    def fulfill_api(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method

        if path not in {"/api/analytics", "/api/tts-event"}:
            record["calls"].append((method, path, request.post_data))

        if path in {"/api/analytics", "/api/tts-event"}:
            route.fulfill(status=204, body="")
        elif path == "/api/greeting":
            route.fulfill(json={"greeting": "Shalom, how can I help?"})
        elif path == "/api/calendar-status":
            route.fulfill(json={"message": None})
        elif path == "/api/dvar-torah":
            route.fulfill(
                json={
                    "parsha_name": "Bereshit",
                    "parsha_name_hebrew": "בראשית",
                    "content": (
                        "Beginnings in Torah are rarely blank slates. They invite us to notice "
                        "what is already present, then choose one faithful next step.\n\n"
                        "A small practice can become a doorway into a wider Jewish life."
                    ),
                    "is_holiday_week": False,
                    "sponsors": [],
                }
            )
        elif path == "/api/conversations" and method == "GET":
            route.fulfill(json={"conversations": conversations})
        elif path == "/api/conversations" and method == "POST":
            conversation = {
                "id": "conversation-synthetic",
                "title": "Beginning a Shabbat practice",
                "first_message": "How can I begin observing Shabbat?",
            }
            conversations[:] = [conversation]
            route.fulfill(status=201, json=conversation)
        elif path == "/api/chat/stream":
            record["chat_requests"].append(request.post_data_json)
            if live_stream:
                route.continue_()
                return
            if queue:
                body = queue.pop(0)
                if body is None:
                    route.abort("connectionreset")
                    return
            else:
                body = stream_body or (
                    'data: {"type":"token","data":"A thoughtful response."}\n\n'
                )
            route.fulfill(
                status=200,
                content_type="text/event-stream; charset=utf-8",
                body=body,
                headers={"Cache-Control": "no-cache"},
            )
        elif path == "/api/credits":
            route.fulfill(json={"credits": credits, "unlimited": False, "tts_credit_cost": 8})
        elif path == "/api/payments/packages":
            route.fulfill(json=PACKAGES)
        elif path.startswith("/api/conversations/") and method == "GET":
            conversation_id = path.rsplit("/", 1)[1]
            messages = (conversation_messages or {}).get(conversation_id)
            if messages is None:
                route.fulfill(status=404, json={"detail": "Conversation not found"})
            else:
                route.fulfill(json={"id": conversation_id, "title": "Synthetic history", "messages": messages})
        elif path.startswith("/api/conversations/") and method in {"PATCH", "DELETE"}:
            route.fulfill(json={"deleted": True} if method == "DELETE" else {"id": path.rsplit("/", 1)[1], **(request.post_data_json or {})})
        elif path == "/api/profile" and method == "GET":
            route.fulfill(json=profile)
        elif path == "/api/profile" and method == "PUT":
            profile.update(request.post_data_json)
            route.fulfill(json=profile)
        elif path == "/api/payments/create-intent":
            route.fulfill(
                json={
                    "client_secret": "pi_synthetic_secret",
                    "customer_session_client_secret": "cuss_synthetic_secret",
                    "publishable_key": "pk_test_synthetic",
                }
            )
        elif path == "/api/payments/create-sponsorship-intent":
            route.fulfill(
                json={
                    "client_secret": "pi_sponsor_synthetic_secret",
                    "customer_session_client_secret": "cuss_sponsor_synthetic_secret",
                    "publishable_key": "pk_test_synthetic",
                }
            )
        else:
            route.fulfill(status=404, json={"detail": f"No synthetic fixture for {method} {path}"})

    page.route("**/api/**", fulfill_api)
    install_stripe_stub(page)
    return record


def wait_for_signed_in_app(page):
    page.locator("#greetingText:not(.hidden)").wait_for()
    page.locator("#sidebarUserName").filter(has_text="Aaron Example").wait_for()


# 320 CSS pixels is the narrowest viewport still in real use (iPhone SE in
# landscape-locked apps, small Android handsets, and a 1280px desktop zoomed
# to 400%, which WCAG 1.4.10 requires to reflow without horizontal scrolling).
NARROW_WIDTH = 320
PUBLIC_PAGES = ("landing.html", "privacy.html")
ALL_PAGES = ("landing.html", "privacy.html", "index.html", "admin.html")


def assert_no_horizontal_overflow(page, label: str):
    """Fail with the offending elements named, not just a bare False."""

    offenders = page.evaluate(
        """
        () => {
          const root = document.documentElement;
          if (root.scrollWidth <= root.clientWidth) return [];
          return Array.from(document.querySelectorAll('*'))
            .filter((el) => {
              const rect = el.getBoundingClientRect();
              return rect.width > 0 && rect.right > root.clientWidth + 1;
            })
            .slice(0, 8)
            .map((el) => `${el.tagName}.${String(el.className).trim().slice(0, 40)}`);
        }
        """
    )
    assert offenders == [], f"{label} overflows horizontally; widest offenders: {offenders}"


# Computes the WCAG 2.1 contrast ratio for every element that renders its own
# text, resolving translucent colors against the real painted backdrop by
# walking up the ancestor chain. Returns only the elements that fall short, so
# an assertion failure names the exact offenders and their ratios.
CONTRAST_AUDIT_JS = r"""
() => {
  const parse = (value) => {
    const match = value.match(/rgba?\(([^)]+)\)/);
    if (!match) return null;
    const parts = match[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const luminance = ({ r, g, b }) => {
    const channel = (value) => {
      value /= 255;
      return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const contrast = (a, b) => {
    const la = luminance(a);
    const lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  const backdrop = (el) => {
    let node = el;
    let stack = null;
    while (node && node.nodeType === 1) {
      const bg = parse(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0) {
        stack = stack ? over(stack, bg) : bg;
        if (stack.a >= 1) return stack;
      }
      node = node.parentElement;
    }
    const page = parse(getComputedStyle(document.body).backgroundColor)
      || { r: 255, g: 255, b: 255, a: 1 };
    return stack ? over(stack, page) : page;
  };

  const SELECTOR = 'h1,h2,h3,h4,h5,h6,p,a,button,label,span,li,td,th,summary,strong,em,time,figcaption';
  const failures = [];
  document.querySelectorAll(SELECTOR).forEach((el) => {
    if (el.closest('[aria-hidden="true"], .sr-only')) return;
    if (el.matches(':disabled') || el.closest(':disabled')) return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || Number(style.opacity) < 0.1) return;
    // Skip wrappers: only elements with their own text nodes are measured.
    const text = Array.from(el.childNodes)
      .filter((node) => node.nodeType === 3 && node.textContent.trim())
      .map((node) => node.textContent.trim())
      .join(' ');
    if (!text) return;

    const color = parse(style.color);
    if (!color || color.a === 0) return;
    const bg = backdrop(el);
    const resolved = color.a < 1 ? over(color, bg) : color;
    const size = parseFloat(style.fontSize);
    const weight = Number(style.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const required = large ? 3 : 4.5;
    const ratio = contrast(resolved, bg);
    if (ratio < required) {
      failures.push({
        text: text.slice(0, 40),
        selector: `${el.tagName}.${String(el.className).trim().slice(0, 40)}`,
        color: style.color,
        background: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`,
        ratio: Math.round(ratio * 100) / 100,
        required,
      });
    }
  });
  return failures;
}
"""


def assert_text_contrast(page, label: str):
    failures = page.evaluate(CONTRAST_AUDIT_JS)
    assert failures == [], f"{label} has text below the WCAG AA contrast threshold: {failures}"


def test_landing_demo_theme_keyboard_and_mobile_overflow(page, frontend_url):
    open_frontend(page, frontend_url, "landing.html", {"width": 1440, "height": 1000})

    assert page.get_by_role("heading", name="Thoughtful Jewish guidance, grounded in sources.").is_visible()
    assert page.get_by_text("Static example").is_visible()
    assert page.get_by_text("Guidance, not psak").first.is_visible()

    source_tab = page.get_by_role("tab", name="Exodus 20:8-11")
    source_tab.focus()
    source_tab.press("End")
    assert page.get_by_role("tab", name="Shabbat 118b").get_attribute("aria-selected") == "true"
    assert "Rabbinic tradition" in page.locator("#source-note").inner_text()

    theme = page.locator("[data-theme-cycle]")
    theme.click()
    theme.click()
    assert page.locator("html").get_attribute("data-theme-preference") == "dark"
    page.reload(wait_until="domcontentloaded")
    assert page.locator("html").get_attribute("data-theme-preference") == "dark"

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.locator(".guided-demo").is_visible()


def test_privacy_policy_reading_surface_theme_and_mobile_overflow(page, frontend_url):
    page_errors = []
    console_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )

    open_frontend(page, frontend_url, "privacy.html", {"width": 1440, "height": 1000})

    assert page.get_by_role("heading", name="A clear account of your information.").is_visible()
    # The effective date moves with each policy revision; assert the element
    # is machine-readable and human-readable rather than pinning one date.
    effective = page.locator(".policy-date time").first
    assert effective.get_attribute("datetime")
    assert effective.inner_text().strip()
    assert page.get_by_text("Share thoughtfully.", exact=True).is_visible()
    assert page.locator("link[rel='canonical']").get_attribute("href") == "https://rebbe.dev/privacy"

    page.get_by_role("link", name="AI and text-to-speech").click()
    assert page.locator("#ai").is_visible()
    assert page.url.endswith("#ai")

    theme = page.locator("[data-theme-cycle]")
    theme.click()
    theme.click()
    assert page.locator("html").get_attribute("data-theme-preference") == "dark"

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.get_by_role("heading", name="A clear account of your information.").is_visible()
    assert page_errors == []
    assert console_errors == []


def test_signed_in_shell_has_labeled_operate_surfaces(page, frontend_url):
    open_frontend(page, frontend_url, "index.html", {"width": 390, "height": 844})

    assert page.locator("#welcomeScreen").is_visible()
    assert page.locator("label[for='messageInput']").inner_text() == "Ask a question"
    assert page.locator("label[for='chatInput']").count() == 1
    # The thread must not be a live region (it would read every token); the
    # finished reply is announced through a dedicated polite region instead.
    assert page.locator("#chatMessages").get_attribute("aria-live") is None
    assert page.locator("#messageLiveRegion").get_attribute("aria-live") == "polite"
    assert page.locator("#purchaseModal").get_attribute("aria-modal") == "true"
    assert page.locator("#sponsorModal").get_attribute("aria-modal") == "true"
    assert page.locator("#messageInput").get_attribute("dir") == "auto"
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_authenticated_welcome_stream_citations_and_human_referral(page, frontend_url):
    events = [
        {
            "type": "session",
            "session_id": "session-synthetic",
            "conversation_id": "conversation-synthetic",
        },
        {
            "type": "metadata",
            "data": {
                "requires_human_referral": True,
                "sources": [
                    {"ref": "Exodus 20:8-11", "verified": True},
                    {"ref": "Mishnah Berakhot 5:1", "verified": False},
                ],
            },
        },
        {
            "type": "token",
            "data": "Begin with one practice that makes room for rest and attention. ",
        },
        {
            "type": "token",
            "data": "A rabbi who knows your circumstances can help with personal guidance.",
        },
        {"type": "message_saved", "message_id": "message-synthetic"},
    ]
    stream_body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    install_app_routes(page, stream_body=stream_body)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)

    assert page.locator("#welcomeScreen").is_visible()
    assert page.locator("#conversationsList").get_by_text(
        "Your conversations will appear here after you ask a question."
    ).is_visible()

    page.locator("#messageInput").fill("How can I begin observing Shabbat?")
    page.locator("#sendBtn").click()

    page.get_by_role("button", name="Exodus 20:8-11, from the library").wait_for()
    assert page.get_by_role("button", name="Mishnah Berakhot 5:1, general knowledge").is_visible()
    assert page.locator(".message-sources").get_by_text("From the library").is_visible()
    assert page.locator(".message-sources").get_by_text("General knowledge").is_visible()
    assert page.locator(".message.assistant .message-content").get_by_text(
        "Begin with one practice"
    ).is_visible()
    assert page.locator("#referralNotice").is_visible()
    assert "A human conversation may help" in page.locator("#referralNotice").inner_text()
    page.wait_for_function(
        "document.querySelector('#appLiveRegion').textContent === "
        "'A human rabbi or counselor may be helpful for this question.'"
    )
    assert page.locator("#chatMessages").get_attribute("aria-busy") == "false"
    assert page_errors == []
    output_dir = ROOT / "output" / "playwright"
    output_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output_dir / "app-chat-desktop-light.png"), full_page=False)


def test_settings_purchase_and_sponsorship_modal_focus_and_escape(page, frontend_url):
    install_app_routes(page)
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)

    page.locator("#userProfile").click()
    assert page.locator("#sidebarDropdown a[href='/privacy']").is_visible()
    page.locator("#settingsBtn").click()
    page.locator("#settingsScreen:not(.hidden)").wait_for()
    assert page.get_by_role("heading", name="Settings").is_visible()
    assert page.locator("label[for='denominationSelect']").is_visible()
    assert page.locator("label[for='bioInput']").is_visible()
    assert page.locator(".settings-policy-link[href='/privacy']").is_visible()
    assert page.locator(".settings-policy-link[href='/terms']").is_visible()

    buy_button = page.locator("#buyCreditsBtn")
    buy_button.click()
    purchase_modal = page.locator("#purchaseModal")
    page.wait_for_function(
        "document.querySelector('#purchaseModal').getAttribute('aria-hidden') === 'false'"
    )
    page.wait_for_function(
        "document.querySelector('#purchaseModal').contains(document.activeElement)"
    )
    assert purchase_modal.evaluate("modal => modal.contains(document.activeElement)")

    last_purchase_focusable = purchase_modal.locator(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), "
        "textarea:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])"
    ).last
    last_purchase_focusable.focus()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "closePurchaseModal"

    page.keyboard.press("Escape")
    purchase_modal.wait_for(state="hidden")
    assert page.evaluate("document.activeElement.id") == "buyCreditsBtn"

    page.locator("#settingsBackBtn").click()
    page.locator("#dvarTorahSection:not(.hidden)").wait_for()
    page.locator("#dvarTorahExpandBtn").click()
    sponsor_button = page.locator("#sponsorDvarBtn")
    sponsor_button.wait_for()
    sponsor_button.click()

    sponsor_modal = page.locator("#sponsorModal")
    page.wait_for_function(
        "document.querySelector('#sponsorModal').getAttribute('aria-hidden') === 'false'"
    )
    page.wait_for_function(
        "document.querySelector('#sponsorModal').contains(document.activeElement)"
    )
    assert sponsor_modal.evaluate("modal => modal.contains(document.activeElement)")
    page.keyboard.press("Escape")
    sponsor_modal.wait_for(state="hidden")
    assert page.evaluate("document.activeElement.id") == "sponsorDvarBtn"


def test_authenticated_mobile_sidebar_reduced_motion_and_zoom_layout(page, frontend_url):
    page.emulate_media(reduced_motion="reduce")
    install_app_routes(page)
    open_frontend(page, frontend_url, "index.html", {"width": 390, "height": 844})
    wait_for_signed_in_app(page)

    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    assert page.locator(".skeleton").first.evaluate(
        "element => getComputedStyle(element).animationIterationCount"
    ) == "1"

    menu_button = page.locator("#welcomeMenuBtn")
    box = menu_button.bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44
    menu_button.click()
    page.locator("#sidebar.open").wait_for()
    assert page.locator("#sidebarOverlay").get_attribute("aria-hidden") == "false"
    assert menu_button.get_attribute("aria-expanded") == "true"

    # The internal rail control must close the mobile drawer, not leave an
    # invisible overlay intercepting the workspace.
    page.locator("#sidebarToggle").click()
    assert page.locator("#sidebar").get_attribute("class") == "sidebar"
    assert page.locator("#sidebarOverlay").get_attribute("aria-hidden") == "true"

    menu_button.click()
    page.locator("#sidebarOverlay").click(position={"x": 380, "y": 420})
    assert page.locator("#sidebar").get_attribute("class") == "sidebar"
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

    # A 720 CSS-pixel layout is the effective viewport of a 1440px desktop at
    # 200% browser zoom and should reflow without horizontal page overflow.
    page.set_viewport_size({"width": 720, "height": 900})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_admin_all_views_empty_states_and_mobile_selector(page, frontend_url):
    responses = {
        "overview": {"overview": {}},
        "costs": {"costs": []},
        "users": {"users": [], "total": 0},
        "flagged": {"flagged": []},
        "feedback": {"feedback": []},
        "errors": {"errors": [], "stats": []},
        "purchases": {"purchases": []},
        "sponsorships": {"sponsorships": []},
        "analytics": {"sessions": {}, "referrers": [], "devices": [], "tts": {}},
        "audit-log": {"audit_log": []},
    }

    def fulfill_admin(route):
        key = route.request.url.split("/api/admin/", 1)[1].split("?", 1)[0]
        route.fulfill(json=responses[key])

    page.route("**/api/admin/**", fulfill_admin)
    open_frontend(page, frontend_url, "admin.html", {"width": 1440, "height": 1000})
    page.wait_for_selector("#content[aria-busy='false']")

    tabs = page.locator("#tabs [role='tab']")
    assert tabs.count() == 9
    for index in range(tabs.count()):
        tabs.nth(index).click()
        page.wait_for_selector("#content[aria-busy='false']")
        assert page.locator("#content").inner_text().strip()

    page.set_viewport_size({"width": 390, "height": 844})
    selector = page.locator("#mobileViewSelect")
    assert selector.is_visible()
    selector.select_option("users")
    page.wait_for_selector("#content[aria-busy='false']")
    assert page.locator("#viewTitle").inner_text() == "Users"
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_admin_auth_failure_is_announced(page, frontend_url):
    page.route(
        "**/api/admin/**",
        lambda route: route.fulfill(status=403, json={"detail": "Admin access required"}),
    )
    open_frontend(page, frontend_url, "admin.html", {"width": 1024, "height": 800})
    page.wait_for_selector("#errorBanner:not([hidden])")
    assert page.locator("#errorBanner").inner_text() == "Admin access required"
    assert page.locator("#content").get_attribute("aria-busy") == "false"


def test_admin_credit_mutation_dialog_recovers_from_failure(page, frontend_url):
    mutation_attempts = []

    def fulfill_admin(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method

        if path == "/api/admin/overview":
            route.fulfill(json={"overview": {}})
        elif path == "/api/admin/users" and method == "GET":
            route.fulfill(
                json={
                    "users": [
                        {
                            "id": "user-synthetic",
                            "email": "reader@example.test",
                            "first_name": "Miriam",
                            "last_name": "Reader",
                            "credits": 12,
                            "conversation_count": 3,
                            "message_count": 8,
                            "total_spent_cents": 100,
                            "created_at": "2026-08-12T12:00:00Z",
                            "is_admin": False,
                        }
                    ],
                    "total": 1,
                }
            )
        elif path == "/api/admin/users/user-synthetic/credits" and method == "POST":
            mutation_attempts.append(request.post_data_json)
            if len(mutation_attempts) == 1:
                route.fulfill(status=500, json={"detail": "Synthetic mutation failure."})
            else:
                route.fulfill(json={"credits": 17})
        else:
            route.fulfill(status=404, json={"detail": f"No fixture for {method} {path}"})

    page.route("**/api/admin/**", fulfill_admin)
    open_frontend(page, frontend_url, "admin.html", {"width": 1280, "height": 900})
    page.wait_for_selector("#content[aria-busy='false']")

    page.locator("#tab-users").click()
    page.get_by_text("reader@example.test").first.wait_for()
    credit_button = page.get_by_role("button", name="Credits").first
    credit_button.click()

    action_dialog = page.locator("#actionDialog")
    page.wait_for_function("document.querySelector('#actionDialog').open")
    page.wait_for_function("document.activeElement.id === 'creditDelta'")
    page.locator("#creditDelta").fill("5")
    page.locator("#creditReason").fill("Restore credits after a synthetic support review")
    page.locator("#actionSubmit").click()

    page.locator("#actionState").get_by_text("Synthetic mutation failure.", exact=True).wait_for()
    assert page.locator("#actionState").get_attribute("class") == "action-state error"
    assert action_dialog.evaluate("dialog => dialog.open")
    assert page.locator("#actionSubmit").is_enabled()

    page.locator("#actionSubmit").click()
    page.locator("#actionState").get_by_text(
        "Credit balance updated. New balance: 17.", exact=True
    ).wait_for()
    assert page.locator("#actionState").get_attribute("class") == "action-state success"
    assert mutation_attempts == [
        {"delta": 5, "reason": "Restore credits after a synthetic support review"},
        {"delta": 5, "reason": "Restore credits after a synthetic support review"},
    ]


def test_authenticated_app_visual_matrix_has_no_page_errors_or_overflow(page, frontend_url):
    """Capture the final signed-in shell in both themes and target viewports."""

    install_app_routes(page)
    page_errors = []
    console_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.add_init_script(
        """
        const theme = new URL(window.location.href).searchParams.get('synthetic-theme');
        if (theme) localStorage.setItem('rebbe-theme', theme);
        """
    )
    output_dir = ROOT / "output" / "playwright"
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix = [
        ("light", {"width": 1440, "height": 1000}, "app-desktop-light.png"),
        ("dark", {"width": 1440, "height": 1000}, "app-desktop-dark.png"),
        ("light", {"width": 390, "height": 844}, "app-mobile-light.png"),
        ("dark", {"width": 390, "height": 844}, "app-mobile-dark.png"),
    ]

    for theme, viewport, filename in matrix:
        page.set_viewport_size(viewport)
        page.goto(
            f"{frontend_url}/index.html?synthetic-theme={theme}",
            wait_until="domcontentloaded",
        )
        wait_for_signed_in_app(page)
        page.locator("#dvarTorahSection:not(.hidden)").wait_for()
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        page.wait_for_function(
            "Array.from(document.images).every((image) => image.complete)"
        )
        assert page.locator("html").get_attribute("data-theme-preference") == theme
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        page.screenshot(path=str(output_dir / filename), full_page=False)
        # Let the tiny threaded fixture server finish writing any deferred font
        # or icon response before the next matrix navigation cancels it.
        page.wait_for_timeout(150)

    assert page_errors == []
    assert console_errors == []


def test_every_surface_reflows_at_320_css_pixels(page, frontend_url):
    """WCAG 1.4.10: content must reflow to 320px without horizontal scrolling.

    The rest of the suite starts at 390px, which leaves the narrowest real
    devices -- and a 1280px desktop zoomed to 400% -- uncovered.
    """

    install_app_routes(page)
    for filename in ALL_PAGES:
        open_frontend(page, frontend_url, filename, {"width": NARROW_WIDTH, "height": 800})
        if filename == "index.html":
            wait_for_signed_in_app(page)
        page.wait_for_timeout(200)
        assert_no_horizontal_overflow(page, f"{filename} at {NARROW_WIDTH}px")


def test_public_pages_load_without_page_or_console_errors(page, frontend_url):
    """The signed-in shell is already covered by the visual matrix; the two
    pages a first-time visitor actually lands on were not."""

    page_errors = []
    console_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )

    for filename in PUBLIC_PAGES:
        for width in (NARROW_WIDTH, 768, 1440):
            open_frontend(page, frontend_url, filename, {"width": width, "height": 900})
            # The feature images are loading="lazy", so a broken one is never
            # requested and never reports while it sits below the fold.
            # Promoting them to eager fetches every image the page references
            # regardless of scroll position, which is what we actually want to
            # assert -- and it avoids depending on scroll geometry, since these
            # pages scroll on <body> rather than the viewport.
            page.evaluate(
                """
                () => {
                  document.querySelectorAll('img[loading="lazy"]').forEach((image) => {
                    image.loading = 'eager';
                    // Re-assigning src restarts source selection for an <img>
                    // the lazy loader has already skipped.
                    if (!image.currentSrc) image.src = image.src;
                  });
                }
                """
            )
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_function(
                "Array.from(document.images).every((image) => image.complete)"
            )
            assert page.evaluate(
                "Array.from(document.images).every((image) => image.naturalWidth > 0)"
            ), f"{filename} at {width}px has an image that failed to decode"
            assert_no_horizontal_overflow(page, f"{filename} at {width}px")

    assert page_errors == []
    assert console_errors == []


def test_text_meets_wcag_aa_contrast_in_both_themes(page, frontend_url):
    """Guards the palette itself.

    Nothing in CI checked contrast before this: the Lighthouse accessibility
    score in the pull request was a manual run over the public pages only, so
    a token misapplied on an operator surface (a border color used as text,
    say) could ship unnoticed.
    """

    install_app_routes(page)
    for filename in ALL_PAGES:
        for theme in ("light", "dark"):
            page.add_init_script(
                f"try {{ localStorage.setItem('rebbe-theme', '{theme}'); }} catch (error) {{}}"
            )
            open_frontend(page, frontend_url, filename, {"width": 1280, "height": 900})
            if filename == "index.html":
                wait_for_signed_in_app(page)
            page.wait_for_timeout(250)
            assert page.locator("html").get_attribute("data-theme") == theme
            assert_text_contrast(page, f"{filename} [{theme}]")


def test_icon_controls_survive_forced_colors(page, frontend_url):
    """Windows High Contrast replaces author colors with a system palette.

    `.ph-icon` paints a masked shape with background-color, which that mode
    rewrites to the system Canvas -- without an explicit escape every
    icon-only control renders as an empty box.
    """

    page.emulate_media(forced_colors="active")
    install_app_routes(page)
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)

    assert page.evaluate("matchMedia('(forced-colors: active)').matches")

    icons = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('.ph-icon'))
          .filter((el) => el.getBoundingClientRect().width > 0)
          .slice(0, 12)
          .map((el) => {
            const style = getComputedStyle(el);
            return {
              adjust: style.forcedColorAdjust,
              background: style.backgroundColor,
              masked: style.maskImage !== 'none' || style.webkitMaskImage !== 'none',
            };
          })
        """
    )
    assert icons, "expected rendered .ph-icon glyphs in the signed-in shell"
    for icon in icons:
        assert icon["adjust"] == "none", f"masked icon would be repainted to Canvas: {icon}"
        assert icon["masked"], f"icon lost its mask under forced colors: {icon}"

    # The focus ring cannot rely on box-shadow here: forced-colors drops shadows.
    page.locator("#newChatBtn").focus()
    focus_style = page.evaluate(
        """
        () => {
          const style = getComputedStyle(document.activeElement);
          return { outlineWidth: style.outlineWidth, outlineStyle: style.outlineStyle };
        }
        """
    )
    assert focus_style["outlineStyle"] != "none"
    assert float(focus_style["outlineWidth"].replace("px", "")) >= 2


def test_credit_balance_keeps_its_numeric_emphasis(page, frontend_url):
    """loadCredits() toggles `.credits-value` for a numeric balance.

    The class carried no rule at all after the rebrand, so the balance
    silently rendered at plain body emphasis.
    """

    install_app_routes(page)
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)

    page.locator("#userProfile").click()
    page.locator("#settingsBtn").click()
    page.locator("#settingsScreen:not(.hidden)").wait_for()

    credits = page.locator("#creditsValue")
    credits.filter(has_text="12").wait_for()
    assert "credits-value" in (credits.get_attribute("class") or "")

    styling = page.evaluate(
        """
        () => {
          const el = document.getElementById('creditsValue');
          const emphasized = getComputedStyle(el);
          const label = getComputedStyle(document.querySelector('.settings-row-label'));
          const probe = document.createElement('span');
          probe.className = 'settings-row-value';
          el.parentElement.appendChild(probe);
          const plain = getComputedStyle(probe);
          const result = {
            color: emphasized.color,
            plainColor: plain.color,
            fontSize: parseFloat(emphasized.fontSize),
            plainFontSize: parseFloat(plain.fontSize),
            labelColor: label.color,
          };
          probe.remove();
          return result;
        }
        """
    )
    assert styling["color"] != styling["plainColor"], (
        "a numeric balance should not paint the same as an unclassed value: "
        f"{styling}"
    )
    assert styling["fontSize"] > styling["plainFontSize"], styling


def test_payment_form_repaints_when_the_theme_changes(page, frontend_url):
    """Stripe Elements renders cross-origin and cannot inherit CSS variables.

    Without an explicit update() the card form keeps whichever theme it
    mounted under, so toggling to dark leaves a white form on a dark modal.
    """

    install_app_routes(page)
    page.add_init_script("try { localStorage.setItem('rebbe-theme', 'light'); } catch (error) {}")
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)

    page.locator("#userProfile").click()
    page.locator("#settingsBtn").click()
    page.locator("#settingsScreen:not(.hidden)").wait_for()
    page.locator("#buyCreditsBtn").click()
    page.wait_for_function(
        "document.querySelector('#purchaseModal').getAttribute('aria-hidden') === 'false'"
    )
    page.wait_for_function("window.__stripeAppearances.created.length > 0")

    created = page.evaluate("window.__stripeAppearances.created.at(-1)")
    assert created["theme"] == "stripe", created

    page.evaluate("window.RebbeTheme.apply('dark', true)")
    page.wait_for_function("window.__stripeAppearances.updated.length > 0")

    updated = page.evaluate("window.__stripeAppearances.updated.at(-1)")
    assert updated["theme"] == "night", updated
    assert updated["variables"]["colorBackground"] == "#161f2c", updated


# ---------------------------------------------------------------------------
# Chat experience v2: streaming, controls, safety, citations, error codes.
# ---------------------------------------------------------------------------


def start_chat(page, frontend_url, text="How can I begin observing Shabbat?", viewport=None):
    open_frontend(page, frontend_url, "index.html", viewport or {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)
    page.locator("#messageInput").fill(text)
    page.locator("#messageInput").press("Enter")


@pytest.fixture
def live_stream_plan():
    """Script the streaming server for one test and reset it afterwards."""

    FrontendHandler.stream_requests = []

    def plan(events):
        FrontendHandler.stream_plan = events

    yield plan
    FrontendHandler.stream_plan = []
    FrontendHandler.stream_requests = []


def test_streaming_renders_incrementally_and_stop_keeps_partial_answer(page, frontend_url, live_stream_plan):
    live_stream_plan(
        [
            (0, {"type": "session", "session_id": "s1", "conversation_id": "conversation-synthetic", "request_id": "r"}),
            (0, {"type": "status", "stage": "sources", "label": "Looking in the sources…"}),
            (0.6, {"type": "token", "data": "## Beginning\n\nShabbat begins with a pause. "}),
            (0.1, {"type": "token", "data": "Light candles if you can.\n\n"}),
            (0.6, {"type": "token", "data": "- Make one meal special\n"}),
            (0.3, {"type": "token", "data": "- Put the phone away for an hour"}),
            (20, {"type": "token", "data": " this text must never arrive"}),
        ]
    )
    install_app_routes(page, live_stream=True)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    start_chat(page, frontend_url)

    # Optimistic user bubble and the status shimmer before any token.
    assert page.locator(".message.user .message-content").inner_text() == "How can I begin observing Shabbat?"
    page.locator(".thinking-label").filter(has_text="Looking in the sources…").wait_for()
    assert page.locator("#stopBtn").is_visible()
    assert page.locator("#chatSendBtn").is_hidden()

    body = page.locator(".message.assistant .message-content")
    body.locator("h2").filter(has_text="Beginning").wait_for()
    paragraph = body.locator("p").first
    paragraph.filter(has_text="Light candles").wait_for()
    handle = paragraph.element_handle()
    page.evaluate("el => { el.dataset.probe = 'kept'; }", handle)

    body.locator("li").filter(has_text="Put the phone away").wait_for()
    # Completed blocks are never re-rendered while later blocks stream in.
    assert handle.evaluate("el => el.isConnected && el.dataset.probe === 'kept'")
    assert page.locator(".thinking").count() == 0
    assert page.locator("#chatMessages").get_attribute("aria-busy") == "true"

    page.locator("#stopBtn").click()
    page.locator("#chatSendBtn").wait_for(state="visible")
    assert page.locator("#stopBtn").is_hidden()
    assert page.locator(".message.assistant .message-flag").inner_text() == "Stopped"
    assert "Put the phone away" in body.inner_text()
    assert "never arrive" not in body.inner_text()
    assert page.locator(".message.assistant.is-last .regenerate-btn").is_visible()
    assert page.locator("#chatMessages").get_attribute("aria-busy") == "false"

    request = FrontendHandler.stream_requests[0]
    assert request["message"] == "How can I begin observing Shabbat?"
    assert request["conversation_id"] == "conversation-synthetic"
    assert request["request_id"]
    assert page_errors == []


def test_regenerate_replaces_the_last_answer_with_a_new_request(page, frontend_url):
    first = sse(
        [
            {"type": "session", "session_id": "s1", "conversation_id": "conversation-synthetic"},
            {"type": "token", "data": "The first answer."},
            {"type": "message_saved", "message_id": "m1"},
            {"type": "done", "message_id": "m1", "credits_remaining": 11, "charged": True},
        ]
    )
    second = sse(
        [
            {"type": "token", "data": "A better, regenerated answer."},
            {"type": "done", "message_id": "m2", "credits_remaining": 10, "charged": True},
        ]
    )
    record = install_app_routes(page, stream_bodies=[first, second])
    start_chat(page, frontend_url)
    page.locator(".message.assistant .message-content").filter(has_text="The first answer.").wait_for()
    assert page.locator("#creditsPillValue").inner_text() == "11 credits"

    page.locator(".message.assistant.is-last .regenerate-btn").click()
    page.locator(".message.assistant .message-content").filter(has_text="regenerated answer").wait_for()
    assert page.locator(".message.assistant").count() == 1
    assert page.locator(".message.user").count() == 1
    assert page.locator("#creditsPillValue").inner_text() == "10 credits"

    regen = record["chat_requests"][1]
    assert regen["regenerate"] is True
    assert regen["message"] == "How can I begin observing Shabbat?"
    assert regen["request_id"] != record["chat_requests"][0]["request_id"]


def test_edit_and_resend_sends_edit_message_id(page, frontend_url):
    history = {
        "conversation-old": [
            {"id": "u1", "role": "user", "content": "What is havdalah?", "created_at": "2026-10-30T12:00:00Z"},
            {"id": "a1", "role": "assistant", "content": "Havdalah closes Shabbat.", "created_at": "2026-10-30T12:00:05Z", "metadata": {}},
        ]
    }
    reply = sse([{"type": "token", "data": "Here is how havdalah works at home."}, {"type": "done", "message_id": "a2"}])
    record = install_app_routes(
        page,
        stream_bodies=[reply],
        conversation_messages=history,
        initial_conversations=[{"id": "conversation-old", "title": "Havdalah", "updated_at": "2026-10-30T12:00:05Z"}],
    )
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)
    page.locator(".conversation-item[data-id='conversation-old'] .conversation-open").click()
    page.locator(".message.assistant .message-content").filter(has_text="Havdalah closes Shabbat.").wait_for()
    assert page.evaluate("location.pathname") == "/c/conversation-old"

    page.locator(".message.user.is-last").hover()
    page.locator(".message.user.is-last .edit-btn").click()
    editor = page.locator(".edit-input")
    editor.fill("How do I make havdalah at home?")
    editor.press("Enter")
    page.locator(".message.assistant .message-content").filter(has_text="havdalah works at home").wait_for()
    assert page.locator(".message.assistant").count() == 1
    assert page.locator(".message.user .message-content").inner_text() == "How do I make havdalah at home?"
    sent = record["chat_requests"][0]
    assert sent["edit_message_id"] == "u1"
    assert sent["message"] == "How do I make havdalah at home?"
    assert sent["conversation_id"] == "conversation-old"


def test_safety_card_renders_before_any_token_and_cannot_be_dismissed(page, frontend_url, live_stream_plan):
    live_stream_plan(
        [
            (0, {"type": "session", "session_id": "s1", "conversation_id": "conversation-synthetic"}),
            (
                0,
                {
                    "type": "safety_resources",
                    "level": "crisis",
                    "title": "You deserve support right now",
                    "message": "If you might act on thoughts of suicide, please reach out now.",
                    "resources": [
                        {
                            "name": "988 Suicide & Crisis Lifeline",
                            "description": "Free, confidential, 24/7",
                            "phone": "988",
                            "sms": "988",
                            "url": "https://988lifeline.org",
                            "region": "US",
                        },
                        {"name": "Crisis Text Line", "sms": "HOME to 741741", "url": "https://www.crisistextline.org", "region": "US"},
                    ],
                },
            ),
            (1.2, {"type": "token", "data": "I am really glad you said something."}),
            (0, {"type": "done", "charged": False}),
        ]
    )
    install_app_routes(page, live_stream=True, credits=2)
    start_chat(page, frontend_url, text="I don't want to be here anymore")

    card = page.locator(".message.assistant .safety-card")
    card.wait_for()
    # Shown while no token has arrived yet.
    assert page.locator(".message.assistant .message-content").inner_text().strip() == ""
    assert card.get_by_role("heading", name="You deserve support right now").is_visible()
    assert card.locator("a[href='tel:988']").is_visible()
    assert card.locator("a[href^='sms:741741']").inner_text().strip() == "Text HOME to 741741"
    assert card.get_by_text("US").first.is_visible()
    assert card.locator("button").count() == 0, "the card must not be dismissible during the turn"
    # No purchase nudge during a crisis turn, even at a low balance.
    assert page.locator("#creditsHint").is_hidden()

    page.locator(".message.assistant .message-content").filter(has_text="glad you said").wait_for()
    order = page.evaluate(
        """() => {
          const card = document.querySelector('.message.assistant .safety-card');
          const body = document.querySelector('.message.assistant .message-content');
          return !!(card.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING);
        }"""
    )
    assert order, "safety card must sit above the answer text"
    assert card.is_visible()


def test_safety_card_is_restored_from_history(page, frontend_url):
    history = {
        "c-safety": [
            {"id": "u1", "role": "user", "content": "I feel hopeless", "created_at": "2026-10-30T12:00:00Z"},
            {
                "id": "a1",
                "role": "assistant",
                "content": "Thank you for telling me.",
                "created_at": "2026-10-30T12:00:05Z",
                "metadata": {
                    "safety_resources": {
                        "level": "crisis",
                        "title": "Support is available",
                        "message": "You can talk to someone now.",
                        "resources": [{"name": "ERAN", "phone": "1201", "region": "Israel", "url": "https://www.eran.org.il"}],
                    }
                },
            },
        ]
    }
    install_app_routes(page, conversation_messages=history)
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)
    page.evaluate("history.pushState({}, '', '/c/c-safety'); dispatchEvent(new PopStateEvent('popstate'))")
    card = page.locator(".message.assistant .safety-card")
    card.wait_for()
    assert card.locator("a[href='tel:1201']").is_visible()
    assert card.get_by_text("Israel").is_visible()


def test_citation_markers_open_the_sources_panel(page, frontend_url):
    events = [
        {"type": "session", "session_id": "s1", "conversation_id": "conversation-synthetic"},
        {"type": "metadata", "data": {"sources": [{"ref": "Shulchan Arukh OC 263", "verified": False}]}},
        {"type": "token", "data": "Remember the Sabbath day to keep it holy."},
        {
            "type": "citation",
            "n": 1,
            "source": {
                "title": "Exodus",
                "ref": "Exodus 20:8",
                "url": "https://www.sefaria.org/Exodus.20.8",
                "excerpt": "Remember the sabbath day and keep it holy.",
                "kind": "library",
            },
        },
        {"type": "token", "data": " Rest is part of the commandment."},
        {"type": "done", "message_id": "m1"},
    ]
    install_app_routes(page, stream_body=sse(events))
    start_chat(page, frontend_url)

    marker = page.locator(".message.assistant .message-content sup .cite-marker")
    marker.wait_for()
    assert marker.inner_text() == "1"
    # The marker sits where the citation event arrived, after the first sentence.
    assert page.evaluate(
        """() => {
          const p = document.querySelector('.message.assistant .message-content p');
          return p.textContent.indexOf('1') > p.textContent.indexOf('holy.')
              && p.textContent.indexOf('1') < p.textContent.indexOf('Rest');
        }"""
    )
    assert page.get_by_role("button", name="Source 1: Exodus 20:8, from the library").is_visible()
    assert page.get_by_role("button", name="Shulchan Arukh OC 263, general knowledge").is_visible()

    marker.click()
    panel = page.locator("#sourcesPanel")
    panel.wait_for()
    item = panel.locator(".source-item.highlighted")
    assert "Exodus 20:8" in item.inner_text()
    assert "From the library" in item.inner_text()
    assert item.locator("blockquote").inner_text() == "Remember the sabbath day and keep it holy."
    link = item.get_by_role("link", name="Open on Sefaria (opens in a new tab)")
    assert link.get_attribute("href") == "https://www.sefaria.org/Exodus.20.8"
    assert link.get_attribute("rel") == "noopener noreferrer"
    assert "General knowledge" in panel.locator(".source-item-general").inner_text()

    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    assert page.evaluate("document.activeElement.classList.contains('cite-marker')")


def test_markdown_is_sanitized_and_links_open_safely(page, frontend_url):
    events = [
        {"type": "token", "data": "<img src=x onerror=\"window.__xss=1\"> **bold** [Sefaria](https://www.sefaria.org) "},
        {"type": "token", "data": "[bad](javascript:window.__xss=2)\n\nשבת שלום"},
        {"type": "done"},
    ]
    install_app_routes(page, stream_body=sse(events))
    start_chat(page, frontend_url)
    body = page.locator(".message.assistant .message-content")
    body.locator("strong").filter(has_text="bold").wait_for()
    assert page.evaluate("window.__xss") is None
    assert body.locator("img").count() == 0
    assert body.locator("a[href^='javascript']").count() == 0
    link = body.get_by_role("link", name="Sefaria")
    assert link.get_attribute("target") == "_blank"
    assert link.get_attribute("rel") == "noopener noreferrer"
    assert body.locator("p").last.get_attribute("dir") == "auto"


def test_no_credits_opens_the_purchase_sheet_and_keeps_the_draft(page, frontend_url):
    events = [
        {"type": "session", "session_id": "s1", "conversation_id": "conversation-synthetic"},
        {"type": "error", "message": "You are out of credits.", "code": "no_credits"},
    ]
    install_app_routes(page, stream_body=sse(events), credits=0)
    start_chat(page, frontend_url, text="Can I light candles late?")

    page.wait_for_function("document.querySelector('#purchaseModal').getAttribute('aria-hidden') === 'false'")
    assert "out of credits" in page.locator("#purchaseModalReason").inner_text()
    assert "contact support" not in page.locator("#purchaseModal").inner_text().lower()
    recommended = page.locator(".package-card[data-package='credits_160']")
    recommended.wait_for()
    assert recommended.get_attribute("aria-pressed") == "true"
    assert page.locator(".package-card").count() == 3
    assert page.locator(".package-card[aria-pressed='true']").count() == 1

    page.keyboard.press("Escape")
    page.locator("#purchaseModal").wait_for(state="hidden")
    # The draft is back in a composer and no orphaned bubbles remain.
    assert page.locator(".message").count() == 0
    assert page.locator("#messageInput").input_value() == "Can I light candles late?"


def test_http_402_and_rate_limit_and_provider_errors_have_next_actions(page, frontend_url):
    def fulfill(route):
        route.fulfill(status=402, json={"detail": "Out of credits", "code": "no_credits"})

    install_app_routes(page)
    page.route("**/api/chat/stream", fulfill)
    start_chat(page, frontend_url, text="First question")
    page.wait_for_function("document.querySelector('#purchaseModal').getAttribute('aria-hidden') === 'false'")
    page.keyboard.press("Escape")

    page.unroute("**/api/chat/stream", fulfill)
    page.route(
        "**/api/chat/stream",
        lambda route: route.fulfill(status=200, content_type="text/event-stream",
                                    body=sse([{"type": "error", "message": "Slow down", "code": "rate_limited", "detail": {"retry_after": 3}}])),
    )
    page.locator("#sendBtn").click()
    error = page.locator(".message.assistant .inline-error")
    error.wait_for()
    assert "sending messages quickly" in error.inner_text()
    assert "try again in" in error.inner_text()
    page.locator(".inline-error").get_by_role("button", name="Try again").wait_for(timeout=6000)


def test_network_failure_retries_with_the_same_request_id(page, frontend_url):
    reply = sse([{"type": "token", "data": "Recovered answer."}, {"type": "done", "message_id": "m1"}])
    record = install_app_routes(page, stream_bodies=[None, reply])
    start_chat(page, frontend_url)
    retry = page.locator(".message.assistant .inline-error").get_by_role("button", name="Retry")
    retry.wait_for()
    assert "Connection lost" in page.locator(".inline-error").inner_text()
    retry.click()
    page.locator(".message.assistant .message-content").filter(has_text="Recovered answer.").wait_for()
    assert page.locator(".message.user").count() == 1
    assert page.locator(".message.assistant").count() == 1
    first, second = record["chat_requests"]
    assert first["request_id"] == second["request_id"]


def test_provider_unavailable_offers_retry_and_finished_reply_is_announced(page, frontend_url):
    reply = sse([{"type": "token", "data": "Second time lucky."}, {"type": "done"}])
    failure = sse([{"type": "error", "message": "Overloaded", "code": "provider_unavailable"}])
    install_app_routes(page, stream_bodies=[failure, reply])
    start_chat(page, frontend_url)
    page.locator(".inline-error").get_by_role("button", name="Retry").click()
    page.locator(".message.assistant .message-content").filter(has_text="Second time lucky.").wait_for()
    page.wait_for_function(
        "document.querySelector('#messageLiveRegion').textContent === 'rebbe.dev replied: Second time lucky.'"
    )


def test_conversation_search_rename_and_delete_with_undo(page, frontend_url):
    conversations = [
        {"id": "c1", "title": "Shabbat candles", "updated_at": "2026-10-31T09:00:00Z"},
        {"id": "c2", "title": "Kashrut at work", "updated_at": "2026-10-20T09:00:00Z"},
    ]
    record = install_app_routes(page, initial_conversations=conversations)
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)
    rows = page.locator(".conversation-item")
    rows.first.wait_for()
    assert rows.count() == 2

    page.locator("#conversationSearch").fill("kash")
    assert rows.count() == 1
    assert rows.first.inner_text().strip() == "Kashrut at work"
    page.locator("#conversationSearch").fill("")

    page.locator(".conversation-item[data-id='c1'] .conversation-menu-btn").click()
    page.get_by_role("menuitem", name="Rename").click()
    page.locator(".conversation-rename").fill("Candle lighting times")
    page.locator(".conversation-rename").press("Enter")
    page.locator(".conversation-title").filter(has_text="Candle lighting times").wait_for()
    assert any(m == "PATCH" and p == "/api/conversations/c1" and "Candle lighting times" in (b or "")
               for m, p, b in record["calls"])

    page.locator(".conversation-item[data-id='c2'] .conversation-menu-btn").click()
    page.get_by_role("menuitem", name="Delete").click()
    assert page.locator(".conversation-item[data-id='c2']").count() == 0
    page.locator(".toast").get_by_role("button", name="Undo").click()
    page.locator(".conversation-item[data-id='c2']").wait_for()
    page.wait_for_timeout(5400)
    assert not any(m == "DELETE" for m, _p, _b in record["calls"]), "undo must cancel the delayed DELETE"


def test_keyboard_shortcuts_and_per_conversation_drafts(page, frontend_url):
    install_app_routes(page)
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)
    page.locator("#newChatBtn").focus()
    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "messageInput"
    page.keyboard.type("Draft about Sukkot")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("second line")
    assert page.locator("#messageInput").input_value() == "Draft about Sukkot\nsecond line"
    page.wait_for_timeout(400)
    page.reload(wait_until="domcontentloaded")
    wait_for_signed_in_app(page)
    assert page.locator("#messageInput").input_value() == "Draft about Sukkot\nsecond line"
    page.locator("#conversationSearch").focus()
    page.keyboard.press("Control+k")
    assert page.locator("#welcomeScreen").is_visible()


def test_settings_offers_export_and_typed_account_deletion(page, frontend_url):
    record = install_app_routes(page)
    page.route("**/api/account", lambda route: route.fulfill(status=500, json={"detail": "Synthetic failure"}))
    open_frontend(page, frontend_url, "index.html", {"width": 1280, "height": 900})
    wait_for_signed_in_app(page)
    page.locator("#userProfile").click()
    page.locator("#settingsBtn").click()
    page.locator("#settingsScreen:not(.hidden)").wait_for()
    assert page.locator("#exportDataBtn").is_visible()
    assert page.locator("#settingsTermsLink").get_attribute("href") == "/terms"

    page.locator("#deleteAccountBtn").click()
    page.wait_for_function("document.querySelector('#deleteAccountModal').getAttribute('aria-hidden') === 'false'")
    confirm = page.locator("#confirmDeleteAccount")
    assert confirm.is_disabled()
    page.locator("#deleteAccountConfirm").fill("delete")
    assert confirm.is_disabled()
    page.locator("#deleteAccountConfirm").fill("DELETE")
    assert confirm.is_enabled()
    confirm.click()
    page.locator("#deleteAccountError").filter(has_text="Synthetic failure").wait_for()
    page.keyboard.press("Escape")
    page.locator("#deleteAccountModal").wait_for(state="hidden")
    assert page.evaluate("document.activeElement.id") == "deleteAccountBtn"
    del record


def test_speak_defaults_to_browser_voice_and_offers_premium(page, frontend_url):
    page.add_init_script(
        """
        window.__spoken = [];
        window.speechSynthesis.speak = (u) => { window.__spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 50); };
        """
    )
    install_app_routes(page, stream_body=sse([{"type": "token", "data": "Listen to this."}, {"type": "done", "message_id": "m1"}]))
    page.route("**/api/speak", lambda route: route.fulfill(status=402, json={"detail": "Not enough credits", "code": "no_credits"}))
    start_chat(page, frontend_url)
    page.locator(".message.assistant .speak-btn").click()
    menu = page.locator(".speak-menu")
    assert menu.get_by_text("Device voice · free").is_visible()
    assert menu.get_by_text("8 credits").is_visible()
    menu.get_by_role("menuitem").first.click()
    page.wait_for_function("window.__spoken.length === 1")
    assert page.evaluate("window.__spoken[0]") == "Listen to this."

    page.locator(".message.assistant .speak-btn").click()
    page.locator(".speak-menu").get_by_role("menuitem", name="Premium voice 8 credits").click()
    page.wait_for_function("document.querySelector('#purchaseModal').getAttribute('aria-hidden') === 'false'")
    assert "premium voice" in page.locator("#purchaseModalReason").inner_text().lower()


def test_mobile_composer_targets_and_bottom_sheet(page, frontend_url):
    install_app_routes(page, stream_body=sse([{"type": "token", "data": "Short answer."}, {"type": "done"}]), credits=3)
    start_chat(page, frontend_url, viewport={"width": 390, "height": 844})
    page.locator(".message.assistant .message-content").filter(has_text="Short answer.").wait_for()
    for selector in ("#chatSendBtn", "#creditsPill", "#menuBtn", ".message.assistant .copy-btn"):
        box = page.locator(selector).bounding_box()
        assert box and box["height"] >= 44 and box["width"] >= 44, f"{selector} target too small: {box}"
    assert page.locator("#creditsHint").is_visible()
    assert page.locator("#creditsHint").inner_text() == "Running low"
    page.locator("#creditsPill").click()
    page.wait_for_function("document.querySelector('#purchaseModal').getAttribute('aria-hidden') === 'false'")
    sheet = page.locator("#purchaseModal .modal-content").bounding_box()
    assert abs((sheet["y"] + sheet["height"]) - 844) <= 1, "purchase sheet should dock to the bottom on phones"
    assert_no_horizontal_overflow(page, "chat at 390px")

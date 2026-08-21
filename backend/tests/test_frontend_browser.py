"""Dev-only Chromium checks for the redesigned frontend surfaces.

The browser receives synthetic API fixtures. No production data, payment
provider, authentication provider, or language-model call is involved.
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest


pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


class FrontendHandler(SimpleHTTPRequestHandler):
    """Serve frontend files while preserving the production /static prefix."""

    def do_GET(self):
        request_path = urlparse(self.path).path
        if request_path in {"/privacy", "/privacy/"}:
            self.path = "/privacy.html"
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


def install_app_routes(page, *, stream_body: str | None = None):
    """Install a complete, synthetic signed-in session for the app shell."""

    conversations = []
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
            route.fulfill(json={"credits": 12, "unlimited": False})
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
    assert page.locator("time[datetime='2026-08-13']").inner_text() == "August 13, 2026"
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
    assert page.locator("#chatMessages").get_attribute("aria-live") == "polite"
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

    page.get_by_text("Locally matched: Exodus 20:8-11").wait_for()
    assert page.get_by_text("Model knowledge: Mishnah Berakhot 5:1").is_visible()
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
    assert page.locator(".settings-policy-link").get_attribute("href") == "/privacy"

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

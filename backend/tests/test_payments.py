"""Tests for payments.py - Stripe payment endpoints.

Only Stripe (a paid third-party API) is faked. Purchases, sponsorships and
credits live in the real test PostgreSQL (``live_db`` / ``real_db``), users
authenticate with a real signed session cookie, and webhook signatures are
verified by Stripe's own library against a locally signed payload.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import stripe

USER = {
    "id": "user-123",
    "email": "test@example.com",
    "first_name": "Test",
    "last_name": "User",
}
WEBHOOK_SECRET = "whsec_test_secret"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def configured(monkeypatch):
    """Configure Stripe keys on the real settings object (dev environment)."""
    from app import payments

    monkeypatch.setattr(payments.settings, "stripe_secret_key", "sk_test_xxx")
    monkeypatch.setattr(payments.settings, "stripe_publishable_key", "pk_test_xxx")
    monkeypatch.setattr(payments.settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(payments.settings, "environment", "development")
    # Other test modules re-import ``app.*``, so payments' settings object may
    # not be the one ``live_db`` pointed at the test database. Mirror the URL
    # (request ``live_db`` before ``configured`` so it is already set).
    monkeypatch.setattr(payments.settings, "database_url", payments.db.get_settings().database_url)
    return payments.settings


class FakeStripe:
    """Records calls to the Stripe API endpoints the payments module uses."""

    def __init__(self, monkeypatch):
        self.calls = {}
        self.intents = {}
        self.retrieve_error = None
        self._n = 0
        monkeypatch.setattr(stripe.Customer, "create", self._recorder("Customer.create", self._customer))
        monkeypatch.setattr(stripe.PaymentIntent, "create", self._recorder("PaymentIntent.create", self._intent))
        monkeypatch.setattr(stripe.PaymentIntent, "retrieve", self._recorder("PaymentIntent.retrieve", self._retrieve))
        monkeypatch.setattr(stripe.CustomerSession, "create", self._recorder("CustomerSession.create", self._session))

    def _recorder(self, name, impl):
        def call(*args, **kwargs):
            self.calls.setdefault(name, []).append((args, kwargs))
            return impl(*args, **kwargs)
        return call

    def _customer(self, **kwargs):
        self._n += 1
        return SimpleNamespace(id=f"cus_new{self._n}")

    def _intent(self, **kwargs):
        self._n += 1
        pi_id = f"pi_test{self._n}"
        return SimpleNamespace(id=pi_id, client_secret=f"{pi_id}_secret")

    def _session(self, **kwargs):
        return SimpleNamespace(client_secret="cs_test_secret")

    def _retrieve(self, pi_id):
        if self.retrieve_error:
            raise self.retrieve_error
        return self.intents[pi_id]

    def set_intent(self, pi_id, status, metadata):
        self.intents[pi_id] = SimpleNamespace(id=pi_id, status=status, metadata=metadata)


@pytest.fixture
def fake_stripe(monkeypatch):
    return FakeStripe(monkeypatch)


def make_client(user=None):
    """A TestClient for the payments router, logged in as ``user`` if given."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import create_session_token
    from app.payments import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if user:
        client.cookies.set("session", create_session_token(user))
    return client


def signed_webhook(event: dict, secret: str = WEBHOOK_SECRET):
    """Serialize ``event`` and sign it the way Stripe does (v1 HMAC-SHA256)."""
    payload = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return payload, {"stripe-signature": f"t={ts},v1={sig}"}


def freeze_today(monkeypatch, day):
    """Pin the clock the weekly-parsha calculation reads."""
    from app import payments

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(day.year, day.month, day.day, 12, tzinfo=tz or timezone.utc)

    # Patch the module globals payments' own resolve_local_date reads: other
    # test modules re-import ``app.*``, so ``app.dvar_torah`` in sys.modules
    # is not always the module payments was imported with.
    monkeypatch.setitem(payments.resolve_local_date.__globals__, "datetime", _Frozen)


# ---------------------------------------------------------------------------
# Catalog endpoints
# ---------------------------------------------------------------------------


class TestGetPackagesEndpoint:
    """Test GET /api/payments/packages endpoint."""

    def test_get_packages_returns_packages(self):
        """Test that packages endpoint returns available packages."""
        response = make_client().get("/api/payments/packages")

        assert response.status_code == 200
        pkgs = response.json()["packages"]
        assert set(pkgs) == {"credits_55", "credits_160", "credits_400"}
        assert (pkgs["credits_55"]["credits"], pkgs["credits_55"]["price_cents"]) == (55, 200)
        assert (pkgs["credits_160"]["credits"], pkgs["credits_160"]["price_cents"]) == (160, 500)
        assert (pkgs["credits_400"]["credits"], pkgs["credits_400"]["price_cents"]) == (400, 1200)
        assert [k for k, v in pkgs.items() if v.get("recommended")] == ["credits_160"]
        # Retired packages are no longer offered.
        assert "credits_10" not in pkgs and "credits_25" not in pkgs


class TestSponsorshipTiersEndpoint:
    """Test GET /api/payments/sponsorship-tiers endpoint."""

    def test_returns_tiers_and_parsha(self, monkeypatch):
        from datetime import date
        freeze_today(monkeypatch, date(2026, 3, 27))

        response = make_client().get("/api/payments/sponsorship-tiers")

        assert response.status_code == 200
        data = response.json()
        assert data["tiers"]["chai"]["amount_cents"] == 1800
        assert data["tiers"]["tenfold_chai"]["amount_cents"] == 18000
        assert data["parsha"] == {"parsha_name": "Tzav", "parsha_name_hebrew": "צו", "hebrew_year": 5786}

    def test_holiday_week_has_no_parsha(self, monkeypatch):
        from datetime import date
        freeze_today(monkeypatch, date(2026, 4, 3))  # Pesach

        response = make_client().get("/api/payments/sponsorship-tiers")

        assert response.status_code == 200
        assert response.json()["parsha"] is None


# ---------------------------------------------------------------------------
# Credit purchases
# ---------------------------------------------------------------------------


class TestCreateIntentEndpoint:
    """Test POST /api/payments/create-intent endpoint."""

    def test_create_intent_requires_auth(self, configured, fake_stripe):
        response = make_client().post("/api/payments/create-intent", json={"package_id": "credits_55"})

        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]
        assert fake_stripe.calls == {}

    def test_tampered_session_cookie_is_rejected(self, configured, fake_stripe):
        client = make_client()
        client.cookies.set("session", "not-a-signed-token")
        response = client.post("/api/payments/create-intent", json={"package_id": "credits_55"})

        assert response.status_code == 401

    def test_create_intent_invalid_package(self, configured, fake_stripe):
        response = make_client(USER).post("/api/payments/create-intent", json={"package_id": "invalid_package"})

        assert response.status_code == 400
        assert "Invalid package" in response.json()["detail"]
        assert fake_stripe.calls == {}

    def test_retired_package_cannot_be_bought(self, configured, fake_stripe):
        response = make_client(USER).post("/api/payments/create-intent", json={"package_id": "credits_10"})

        assert response.status_code == 400

    def test_create_intent_stripe_not_configured(self, configured, fake_stripe, monkeypatch):
        monkeypatch.setattr(configured, "stripe_secret_key", "")

        response = make_client(USER).post("/api/payments/create-intent", json={"package_id": "credits_55"})

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]
        assert fake_stripe.calls == {}

    def test_create_intent_success_new_customer(self, live_db, configured, fake_stripe):
        """First purchase creates the Stripe customer, the intent, and a pending row."""
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"], "Test", "User")
            response = client.post("/api/payments/create-intent", json={"package_id": "credits_160"})

            assert response.status_code == 200
            data = response.json()
            assert data["customer_session_client_secret"] == "cs_test_secret"
            assert data["publishable_key"] == "pk_test_xxx"

            # Customer created from the session user and persisted.
            [(_, cust_kwargs)] = fake_stripe.calls["Customer.create"]
            assert cust_kwargs == {
                "email": "test@example.com",
                "name": "Test User",
                "metadata": {"workos_user_id": "user-123"},
            }
            customer_id = client.portal.call(live_db.get_stripe_customer_id, USER["id"])
            assert customer_id == "cus_new1"

            # PaymentIntent priced from the package, tagged for fulfillment.
            [(_, pi_kwargs)] = fake_stripe.calls["PaymentIntent.create"]
            assert pi_kwargs["amount"] == 500
            assert pi_kwargs["currency"] == "usd"
            assert pi_kwargs["customer"] == "cus_new1"
            assert pi_kwargs["metadata"] == {
                "user_id": "user-123", "package_id": "credits_160", "credits": "160",
            }
            [(_, cs_kwargs)] = fake_stripe.calls["CustomerSession.create"]
            assert cs_kwargs["customer"] == "cus_new1"
            assert data["client_secret"] == "pi_test2_secret"

            purchase = client.portal.call(live_db.get_purchase_by_intent_id, "pi_test2")
            assert purchase["user_id"] == "user-123"
            assert purchase["status"] == "pending"
            assert (purchase["amount_cents"], purchase["credits_purchased"]) == (500, 160)
            assert purchase["package_id"] == "credits_160"

    def test_create_intent_reuses_existing_customer(self, live_db, configured, fake_stripe):
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.set_stripe_customer_id, USER["id"], "cus_existing")

            response = client.post("/api/payments/create-intent", json={"package_id": "credits_55"})

            assert response.status_code == 200
            assert "Customer.create" not in fake_stripe.calls
            [(_, pi_kwargs)] = fake_stripe.calls["PaymentIntent.create"]
            assert pi_kwargs["customer"] == "cus_existing"
            assert pi_kwargs["amount"] == 200

    def test_stripe_error_returns_500_without_pending_purchase(self, live_db, configured, fake_stripe, monkeypatch):
        def boom(**kwargs):
            raise stripe.error.APIConnectionError("network down")
        monkeypatch.setattr(stripe.PaymentIntent, "create", boom)

        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.set_stripe_customer_id, USER["id"], "cus_existing")

            response = client.post("/api/payments/create-intent", json={"package_id": "credits_55"})

            assert response.status_code == 500
            assert "Payment processing error" in response.json()["detail"]
            assert client.portal.call(live_db.get_user_purchases, USER["id"]) == []


class TestVerifyAndFulfillEndpoint:
    """Test POST /api/payments/verify-and-fulfill endpoint."""

    def test_verify_disabled_in_production(self, configured, fake_stripe, monkeypatch):
        monkeypatch.setattr(configured, "environment", "production")

        response = make_client(USER).post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_x"})

        assert response.status_code == 404
        assert fake_stripe.calls == {}

    def test_verify_requires_auth(self, configured, fake_stripe):
        response = make_client().post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_x"})

        assert response.status_code == 401

    def test_verify_wrong_user(self, live_db, configured, fake_stripe):
        """A payment owned by someone else is never fulfilled."""
        fake_stripe.set_intent("pi_other", "succeeded", {"user_id": "different-user"})
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, "different-user", "other@example.com")
            client.portal.call(live_db.create_purchase, "different-user", "pi_other", "cus_o", 200, 55, "credits_55")
            before = client.portal.call(live_db.get_user_credits, "different-user")

            response = client.post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_other"})

            assert response.status_code == 403
            assert "not found" in response.json()["detail"].lower()
            assert fake_stripe.calls["PaymentIntent.retrieve"] == [(("pi_other",), {})]
            assert client.portal.call(live_db.get_purchase_by_intent_id, "pi_other")["status"] == "pending"
            assert client.portal.call(live_db.get_user_credits, "different-user") == before

    def test_verify_payment_not_succeeded(self, live_db, configured, fake_stripe):
        fake_stripe.set_intent("pi_proc", "processing", {"user_id": USER["id"]})
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.create_purchase, USER["id"], "pi_proc", "cus_1", 200, 55, "credits_55")
            before = client.portal.call(live_db.get_user_credits, USER["id"])

            response = client.post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_proc"})

            assert response.status_code == 200
            assert response.json()["success"] is False
            assert response.json()["status"] == "processing"
            assert client.portal.call(live_db.get_purchase_by_intent_id, "pi_proc")["status"] == "pending"
            assert client.portal.call(live_db.get_user_credits, USER["id"]) == before

    def test_verify_success_adds_credits_exactly_once(self, live_db, configured, fake_stripe):
        fake_stripe.set_intent("pi_ok", "succeeded", {"user_id": USER["id"]})
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.create_purchase, USER["id"], "pi_ok", "cus_1", 500, 160, "credits_160")
            before = client.portal.call(live_db.get_user_credits, USER["id"])

            first = client.post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_ok"})
            second = client.post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_ok"})

            assert first.status_code == 200
            assert first.json() == {
                "success": True, "credits_added": 160, "message": "Added 160 credits to your account",
            }
            assert second.json()["success"] is True
            assert client.portal.call(live_db.get_user_credits, USER["id"]) == before + 160
            assert client.portal.call(live_db.get_purchase_by_intent_id, "pi_ok")["status"] == "completed"

    def test_verify_succeeded_without_purchase_record(self, live_db, configured, fake_stripe):
        fake_stripe.set_intent("pi_orphan", "succeeded", {"user_id": USER["id"]})
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])

            response = client.post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_orphan"})

            assert response.status_code == 200
            assert response.json()["success"] is False
            assert "record not found" in response.json()["message"]

    def test_verify_sponsorship_publishes_dedication(self, live_db, configured, fake_stripe):
        fake_stripe.set_intent("pi_sp", "succeeded", {"user_id": USER["id"], "type": "sponsorship"})
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.create_sponsorship, USER["id"], "pi_sp", 1800,
                               "Sarah bat Avraham", "memory", "Tzav", 5786)

            response = client.post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_sp"})

            assert response.status_code == 200
            assert response.json()["sponsorship"] is True
            assert "Parashat Tzav" in response.json()["message"]
            assert client.portal.call(live_db.list_parsha_sponsors, "Tzav", 5786) == [
                {"dedication": "Sarah bat Avraham", "dedication_type": "memory"}
            ]

    def test_verify_stripe_error_returns_500(self, configured, fake_stripe):
        fake_stripe.retrieve_error = stripe.error.InvalidRequestError("No such payment_intent", "id")

        response = make_client(USER).post("/api/payments/verify-and-fulfill", json={"payment_intent_id": "pi_bad"})

        assert response.status_code == 500
        assert "verification error" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Webhook (production fulfillment)
# ---------------------------------------------------------------------------


def _event(event_type, obj):
    return {"id": "evt_test", "object": "event", "type": event_type, "data": {"object": obj}}


class TestWebhookEndpoint:
    """Test POST /api/payments/webhook endpoint with real signature checks."""

    def test_webhook_not_configured(self, configured, monkeypatch):
        monkeypatch.setattr(configured, "stripe_webhook_secret", "")

        response = make_client().post("/api/payments/webhook", content=b"{}", headers={"stripe-signature": "x"})

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    def test_webhook_missing_signature(self, configured):
        response = make_client().post("/api/payments/webhook", content=b"{}")

        assert response.status_code == 400
        assert "Missing signature" in response.json()["detail"]

    def test_webhook_rejects_wrong_secret(self, live_db, configured):
        payload, headers = signed_webhook(
            _event("payment_intent.succeeded", {"id": "pi_forged", "metadata": {}}), secret="whsec_attacker"
        )
        with make_client() as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.create_purchase, USER["id"], "pi_forged", "cus_1", 200, 55, "credits_55")
            before = client.portal.call(live_db.get_user_credits, USER["id"])

            response = client.post("/api/payments/webhook", content=payload, headers=headers)

            assert response.status_code == 400
            assert "Invalid signature" in response.json()["detail"]
            assert client.portal.call(live_db.get_purchase_by_intent_id, "pi_forged")["status"] == "pending"
            assert client.portal.call(live_db.get_user_credits, USER["id"]) == before

    def test_webhook_rejects_tampered_payload(self, configured):
        payload, headers = signed_webhook(_event("payment_intent.succeeded", {"id": "pi_1", "metadata": {}}))
        tampered = payload.replace("pi_1", "pi_2")

        response = make_client().post("/api/payments/webhook", content=tampered, headers=headers)

        assert response.status_code == 400
        assert "Invalid signature" in response.json()["detail"]

    def test_webhook_payment_succeeded_is_idempotent(self, live_db, configured):
        """Stripe retries deliveries; credits must be added only once."""
        payload, headers = signed_webhook(
            _event("payment_intent.succeeded", {"id": "pi_wh", "status": "succeeded",
                                                "metadata": {"user_id": USER["id"], "credits": "55"}})
        )
        with make_client() as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.create_purchase, USER["id"], "pi_wh", "cus_1", 200, 55, "credits_55")
            before = client.portal.call(live_db.get_user_credits, USER["id"])

            for _ in range(2):
                response = client.post("/api/payments/webhook", content=payload, headers=headers)
                assert response.status_code == 200
                assert response.json() == {"status": "ok"}

            assert client.portal.call(live_db.get_user_credits, USER["id"]) == before + 55
            purchase = client.portal.call(live_db.get_purchase_by_intent_id, "pi_wh")
            assert purchase["status"] == "completed"
            assert purchase["completed_at"] is not None

    def test_webhook_payment_failed(self, live_db, configured):
        payload, headers = signed_webhook(
            _event("payment_intent.payment_failed", {"id": "pi_fail", "status": "requires_payment_method"})
        )
        with make_client() as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.create_purchase, USER["id"], "pi_fail", "cus_1", 200, 55, "credits_55")
            before = client.portal.call(live_db.get_user_credits, USER["id"])

            response = client.post("/api/payments/webhook", content=payload, headers=headers)

            assert response.status_code == 200
            assert client.portal.call(live_db.get_purchase_by_intent_id, "pi_fail")["status"] == "failed"
            assert client.portal.call(live_db.get_user_credits, USER["id"]) == before

    def test_webhook_unhandled_event_is_acknowledged(self, live_db, configured):
        payload, headers = signed_webhook(_event("charge.refunded", {"id": "ch_1"}))
        with make_client() as client:
            response = client.post("/api/payments/webhook", content=payload, headers=headers)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers called by the endpoints and webhook
# ---------------------------------------------------------------------------


class TestGetOrCreateStripeCustomer:
    """Test get_or_create_stripe_customer helper function."""

    async def test_returns_existing_customer(self, real_db, fake_stripe):
        from app.payments import get_or_create_stripe_customer
        await real_db.upsert_user("user-123", "test@example.com")
        await real_db.set_stripe_customer_id("user-123", "cus_existing")

        result = await get_or_create_stripe_customer({"id": "user-123", "email": "test@example.com"})

        assert result == "cus_existing"
        assert "Customer.create" not in fake_stripe.calls

    async def test_creates_and_persists_new_customer(self, real_db, fake_stripe):
        from app.payments import get_or_create_stripe_customer
        await real_db.upsert_user("user-123", "test@example.com")

        result = await get_or_create_stripe_customer(USER)

        assert result == "cus_new1"
        assert fake_stripe.calls["Customer.create"] == [((), {
            "email": "test@example.com",
            "name": "Test User",
            "metadata": {"workos_user_id": "user-123"},
        })]
        assert await real_db.get_stripe_customer_id("user-123") == "cus_new1"
        # Second call reuses the stored mapping.
        assert await get_or_create_stripe_customer(USER) == "cus_new1"
        assert len(fake_stripe.calls["Customer.create"]) == 1

    async def test_customer_without_name_sends_none(self, real_db, fake_stripe):
        from app.payments import get_or_create_stripe_customer
        await real_db.upsert_user("user-9", "anon@example.com")

        await get_or_create_stripe_customer({"id": "user-9", "email": "anon@example.com"})

        assert fake_stripe.calls["Customer.create"][0][1]["name"] is None


class TestHandlePaymentSucceeded:
    """Test handle_payment_succeeded helper function."""

    async def test_completes_purchase(self, real_db):
        from app.payments import handle_payment_succeeded
        await real_db.upsert_user("user-123", "test@example.com")
        await real_db.create_purchase("user-123", "pi_test123", "cus_1", 1200, 400, "credits_400")
        before = await real_db.get_user_credits("user-123")

        await handle_payment_succeeded({"id": "pi_test123"})

        assert await real_db.get_user_credits("user-123") == before + 400
        assert (await real_db.get_purchase_by_intent_id("pi_test123"))["status"] == "completed"

    async def test_handles_missing_purchase_record(self, real_db):
        from app.payments import handle_payment_succeeded

        # Webhook can arrive before the pending row exists; must not raise.
        await handle_payment_succeeded({"id": "pi_unknown"})

        assert await real_db.get_purchase_by_intent_id("pi_unknown") is None


class TestHandlePaymentFailed:
    """Test handle_payment_failed helper function."""

    async def test_marks_purchase_failed(self, real_db):
        from app.payments import handle_payment_failed
        await real_db.upsert_user("user-123", "test@example.com")
        await real_db.create_purchase("user-123", "pi_test123", "cus_1", 200, 55, "credits_55")

        await handle_payment_failed({"id": "pi_test123"})

        assert (await real_db.get_purchase_by_intent_id("pi_test123"))["status"] == "failed"


# ---------------------------------------------------------------------------
# Sponsorships
# ---------------------------------------------------------------------------


class TestCreateSponsorshipIntentEndpoint:
    """Test POST /api/payments/create-sponsorship-intent endpoint."""

    BODY = {"tier_id": "chai", "dedication": "Sarah bat Avraham", "dedication_type": "memory"}

    @pytest.fixture(autouse=True)
    def regular_week(self, monkeypatch):
        from datetime import date
        freeze_today(monkeypatch, date(2026, 3, 27))  # Parashat Tzav 5786

    def test_requires_auth(self, configured, fake_stripe):
        response = make_client().post("/api/payments/create-sponsorship-intent", json=self.BODY)

        assert response.status_code == 401
        assert fake_stripe.calls == {}

    def test_invalid_tier_rejected(self, configured, fake_stripe):
        response = make_client(USER).post("/api/payments/create-sponsorship-intent",
                                          json={**self.BODY, "tier_id": "bogus"})

        assert response.status_code == 400
        assert fake_stripe.calls == {}

    def test_database_not_configured(self, configured, fake_stripe, monkeypatch):
        monkeypatch.setattr(configured, "database_url", "")
        monkeypatch.setattr(configured, "postgres_url", "")
        monkeypatch.setattr(configured, "pghost", "")
        monkeypatch.setattr(configured, "postgres_host", "")

        response = make_client(USER).post("/api/payments/create-sponsorship-intent", json=self.BODY)

        assert response.status_code == 503
        assert "Database" in response.json()["detail"]

    def test_holiday_week_rejected(self, live_db, configured, fake_stripe, monkeypatch):
        from datetime import date
        freeze_today(monkeypatch, date(2026, 4, 3))  # Pesach: no weekly parsha

        response = make_client(USER).post("/api/payments/create-sponsorship-intent", json=self.BODY)

        assert response.status_code == 400
        assert "holiday" in response.json()["detail"].lower()
        assert fake_stripe.calls == {}

    def test_whitespace_only_dedication_rejected(self, live_db, configured, fake_stripe):
        # Passes the raw min_length=2 check but trims to empty - must not
        # create a PaymentIntent or a blank public dedication.
        response = make_client(USER).post("/api/payments/create-sponsorship-intent",
                                          json={**self.BODY, "dedication": "   "})

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
        assert "PaymentIntent.create" not in fake_stripe.calls

    def test_success_creates_intent_and_record(self, live_db, configured, fake_stripe):
        with make_client(USER) as client:
            client.portal.call(live_db.upsert_user, USER["id"], USER["email"])
            client.portal.call(live_db.set_stripe_customer_id, USER["id"], "cus_test123")

            response = client.post("/api/payments/create-sponsorship-intent", json={
                "tier_id": "double_chai",
                "dedication": "  Sarah bat Avraham  ",
                "dedication_type": "memory",
            })

            assert response.status_code == 200
            data = response.json()
            assert data["client_secret"] == "pi_test1_secret"
            assert data["customer_session_client_secret"] == "cs_test_secret"
            assert data["parsha"]["parsha_name"] == "Tzav"

            # PaymentIntent tagged as a sponsorship for webhook dispatch
            [(_, intent_kwargs)] = fake_stripe.calls["PaymentIntent.create"]
            assert intent_kwargs["amount"] == 3600
            assert intent_kwargs["currency"] == "usd"
            assert intent_kwargs["customer"] == "cus_test123"
            assert intent_kwargs["metadata"] == {
                "type": "sponsorship", "user_id": "user-123", "tier_id": "double_chai", "parsha_name": "Tzav",
            }

            # Pending sponsorship row recorded with trimmed dedication; not
            # public until paid.
            [row] = client.portal.call(live_db.admin_list_sponsorships)
            assert row["stripe_payment_intent_id"] == "pi_test1"
            assert row["dedication"] == "Sarah bat Avraham"
            assert row["dedication_type"] == "memory"
            assert row["amount_cents"] == 3600
            assert (row["parsha_name"], row["hebrew_year"]) == ("Tzav", 5786)
            assert row["status"] == "pending"
            assert client.portal.call(live_db.list_parsha_sponsors, "Tzav", 5786) == []


class TestSponsorshipWebhookDispatch:
    """Test that webhook handlers route sponsorship payments correctly."""

    async def _seed(self, db):
        await db.upsert_user("u1", "u1@example.com")
        await db.create_sponsorship("u1", "pi_sponsor1", 1800, "In honor of Leah", "honor", "Tzav", 5786)
        await db.create_purchase("u1", "pi_test123", "cus_1", 200, 55, "credits_55")
        return await db.get_user_credits("u1")

    async def test_succeeded_sponsorship_completes_sponsorship_not_purchase(self, real_db):
        from app.payments import handle_payment_succeeded
        credits = await self._seed(real_db)

        await handle_payment_succeeded({"id": "pi_sponsor1", "metadata": {"type": "sponsorship"}})

        assert await real_db.list_parsha_sponsors("Tzav", 5786) == [
            {"dedication": "In honor of Leah", "dedication_type": "honor"}
        ]
        assert await real_db.get_user_credits("u1") == credits
        assert (await real_db.get_purchase_by_intent_id("pi_test123"))["status"] == "pending"

    async def test_succeeded_purchase_still_completes_purchase(self, real_db):
        from app.payments import handle_payment_succeeded
        credits = await self._seed(real_db)

        await handle_payment_succeeded({"id": "pi_test123", "metadata": {"user_id": "u1"}})

        assert await real_db.get_user_credits("u1") == credits + 55
        assert await real_db.list_parsha_sponsors("Tzav", 5786) == []

    async def test_failed_sponsorship_marks_sponsorship_failed(self, real_db):
        from app.payments import handle_payment_failed
        await self._seed(real_db)

        await handle_payment_failed({"id": "pi_sponsor1", "metadata": {"type": "sponsorship"}})

        [row] = await real_db.admin_list_sponsorships()
        assert row["status"] == "failed"
        assert (await real_db.get_purchase_by_intent_id("pi_test123"))["status"] == "pending"

    async def test_failure_after_completion_keeps_dedication_live(self, real_db):
        """A late failure event must not unpublish a paid dedication."""
        from app.payments import handle_payment_failed, handle_payment_succeeded
        await self._seed(real_db)

        await handle_payment_succeeded({"id": "pi_sponsor1", "metadata": {"type": "sponsorship"}})
        await handle_payment_failed({"id": "pi_sponsor1", "metadata": {"type": "sponsorship"}})

        [row] = await real_db.admin_list_sponsorships()
        assert row["status"] == "completed"

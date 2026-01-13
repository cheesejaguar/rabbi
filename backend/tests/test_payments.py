"""Tests for payments.py - Stripe payment endpoints."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import stripe


class TestGetPackagesEndpoint:
    """Test GET /api/payments/packages endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked dependencies."""
        with patch('app.payments.get_current_user', return_value=None):
            from app.payments import router
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            app = FastAPI()
            app.include_router(router)
            return TestClient(app)

    def test_get_packages_returns_packages(self, client):
        """Test that packages endpoint returns available packages."""
        response = client.get("/api/payments/packages")

        assert response.status_code == 200
        data = response.json()
        assert "packages" in data
        assert "credits_10" in data["packages"]
        assert "credits_25" in data["packages"]
        assert data["packages"]["credits_10"]["credits"] == 10
        assert data["packages"]["credits_10"]["price_cents"] == 100
        assert data["packages"]["credits_25"]["credits"] == 25
        assert data["packages"]["credits_25"]["price_cents"] == 200


class TestCreateIntentEndpoint:
    """Test POST /api/payments/create-intent endpoint."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        return {
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }

    @pytest.fixture
    def client_with_auth(self, mock_user):
        """Create test client with mocked authentication."""
        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.stripe_secret_key = "sk_test_xxx"
                mock_settings.stripe_publishable_key = "pk_test_xxx"
                mock_settings.is_production = False

                from app.payments import router
                from fastapi import FastAPI
                from fastapi.testclient import TestClient

                app = FastAPI()
                app.include_router(router)
                yield TestClient(app)

    @pytest.fixture
    def client_no_auth(self):
        """Create test client without authentication."""
        with patch('app.payments.get_current_user', return_value=None):
            from app.payments import router
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            app = FastAPI()
            app.include_router(router)
            return TestClient(app)

    def test_create_intent_requires_auth(self, client_no_auth):
        """Test that create-intent requires authentication."""
        response = client_no_auth.post(
            "/api/payments/create-intent",
            json={"package_id": "credits_10"}
        )

        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    def test_create_intent_invalid_package(self, client_with_auth):
        """Test that invalid package ID returns 400."""
        response = client_with_auth.post(
            "/api/payments/create-intent",
            json={"package_id": "invalid_package"}
        )

        assert response.status_code == 400
        assert "Invalid package" in response.json()["detail"]

    def test_create_intent_stripe_not_configured(self, mock_user):
        """Test error when Stripe is not configured."""
        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.stripe_secret_key = ""  # Not configured

                from app.payments import router
                from fastapi import FastAPI
                from fastapi.testclient import TestClient

                app = FastAPI()
                app.include_router(router)
                client = TestClient(app)

                response = client.post(
                    "/api/payments/create-intent",
                    json={"package_id": "credits_10"}
                )

                assert response.status_code == 503
                assert "not configured" in response.json()["detail"]

    def test_create_intent_success(self, mock_user):
        """Test successful payment intent creation."""
        mock_payment_intent = MagicMock()
        mock_payment_intent.id = "pi_test123"
        mock_payment_intent.client_secret = "pi_test123_secret"

        mock_customer_session = MagicMock()
        mock_customer_session.client_secret = "cs_test123_secret"

        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.stripe_secret_key = "sk_test_xxx"
                mock_settings.stripe_publishable_key = "pk_test_xxx"
                mock_settings.is_production = False

                with patch('app.payments.db') as mock_db:
                    mock_db.get_stripe_customer_id = AsyncMock(return_value="cus_existing")
                    mock_db.create_purchase = AsyncMock(return_value={"id": "purchase-123"})

                    with patch('app.payments.stripe') as mock_stripe:
                        mock_stripe.PaymentIntent.create.return_value = mock_payment_intent
                        mock_stripe.CustomerSession.create.return_value = mock_customer_session

                        from app.payments import router
                        from fastapi import FastAPI
                        from fastapi.testclient import TestClient

                        app = FastAPI()
                        app.include_router(router)
                        client = TestClient(app)

                        response = client.post(
                            "/api/payments/create-intent",
                            json={"package_id": "credits_10"}
                        )

                        assert response.status_code == 200
                        data = response.json()
                        assert data["client_secret"] == "pi_test123_secret"
                        assert data["customer_session_client_secret"] == "cs_test123_secret"
                        assert data["publishable_key"] == "pk_test_xxx"


class TestVerifyAndFulfillEndpoint:
    """Test POST /api/payments/verify-and-fulfill endpoint."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        return {
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }

    def test_verify_disabled_in_production(self, mock_user):
        """Test that verify-and-fulfill returns 404 in production."""
        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.is_production = True
                mock_settings.stripe_secret_key = "sk_test_xxx"

                from app.payments import router
                from fastapi import FastAPI
                from fastapi.testclient import TestClient

                app = FastAPI()
                app.include_router(router)
                client = TestClient(app)

                response = client.post(
                    "/api/payments/verify-and-fulfill",
                    json={"payment_intent_id": "pi_test123"}
                )

                assert response.status_code == 404

    def test_verify_requires_auth(self):
        """Test that verify-and-fulfill requires authentication."""
        with patch('app.payments.get_current_user', return_value=None):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.is_production = False

                from app.payments import router
                from fastapi import FastAPI
                from fastapi.testclient import TestClient

                app = FastAPI()
                app.include_router(router)
                client = TestClient(app)

                response = client.post(
                    "/api/payments/verify-and-fulfill",
                    json={"payment_intent_id": "pi_test123"}
                )

                assert response.status_code == 401

    def test_verify_wrong_user(self, mock_user):
        """Test that verify fails if payment belongs to different user."""
        mock_payment_intent = MagicMock()
        mock_payment_intent.metadata = {"user_id": "different-user"}
        mock_payment_intent.status = "succeeded"

        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.is_production = False
                mock_settings.stripe_secret_key = "sk_test_xxx"

                with patch('app.payments.stripe.PaymentIntent') as mock_pi:
                    mock_pi.retrieve.return_value = mock_payment_intent

                    from app.payments import router
                    from fastapi import FastAPI
                    from fastapi.testclient import TestClient

                    app = FastAPI()
                    app.include_router(router)
                    client = TestClient(app)

                    response = client.post(
                        "/api/payments/verify-and-fulfill",
                        json={"payment_intent_id": "pi_test123"}
                    )

                    assert response.status_code == 403
                    assert "not found" in response.json()["detail"].lower()

    def test_verify_payment_not_succeeded(self, mock_user):
        """Test that verify returns failure if payment not succeeded."""
        mock_payment_intent = MagicMock()
        mock_payment_intent.metadata = {"user_id": "user-123"}
        mock_payment_intent.status = "processing"

        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.is_production = False
                mock_settings.stripe_secret_key = "sk_test_xxx"

                with patch('app.payments.stripe.PaymentIntent') as mock_pi:
                    mock_pi.retrieve.return_value = mock_payment_intent

                    from app.payments import router
                    from fastapi import FastAPI
                    from fastapi.testclient import TestClient

                    app = FastAPI()
                    app.include_router(router)
                    client = TestClient(app)

                    response = client.post(
                        "/api/payments/verify-and-fulfill",
                        json={"payment_intent_id": "pi_test123"}
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is False
                    assert data["status"] == "processing"

    def test_verify_success(self, mock_user):
        """Test successful verification and fulfillment."""
        mock_payment_intent = MagicMock()
        mock_payment_intent.metadata = {"user_id": "user-123"}
        mock_payment_intent.status = "succeeded"

        with patch('app.payments.get_current_user', return_value=mock_user):
            with patch('app.payments.settings') as mock_settings:
                mock_settings.is_production = False
                mock_settings.stripe_secret_key = "sk_test_xxx"

                with patch('app.payments.stripe.PaymentIntent') as mock_pi:
                    mock_pi.retrieve.return_value = mock_payment_intent

                    with patch('app.payments.db') as mock_db:
                        mock_db.complete_purchase = AsyncMock(return_value={
                            "status": "completed",
                            "credits_purchased": 10,
                        })

                        from app.payments import router
                        from fastapi import FastAPI
                        from fastapi.testclient import TestClient

                        app = FastAPI()
                        app.include_router(router)
                        client = TestClient(app)

                        response = client.post(
                            "/api/payments/verify-and-fulfill",
                            json={"payment_intent_id": "pi_test123"}
                        )

                        assert response.status_code == 200
                        data = response.json()
                        assert data["success"] is True
                        assert data["credits_added"] == 10


class TestWebhookEndpoint:
    """Test POST /api/payments/webhook endpoint."""

    def test_webhook_not_configured(self):
        """Test error when webhook secret is not configured."""
        with patch('app.payments.settings') as mock_settings:
            mock_settings.stripe_webhook_secret = ""
            mock_settings.stripe_secret_key = "sk_test_xxx"

            from app.payments import router
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

            response = client.post(
                "/api/payments/webhook",
                content=b"{}",
                headers={"stripe-signature": "test_sig"}
            )

            assert response.status_code == 503
            assert "not configured" in response.json()["detail"]

    def test_webhook_missing_signature(self):
        """Test error when signature header is missing."""
        with patch('app.payments.settings') as mock_settings:
            mock_settings.stripe_webhook_secret = "whsec_test"
            mock_settings.stripe_secret_key = "sk_test_xxx"

            from app.payments import router
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            app = FastAPI()
            app.include_router(router)
            client = TestClient(app)

            response = client.post(
                "/api/payments/webhook",
                content=b"{}"
            )

            assert response.status_code == 400
            assert "Missing signature" in response.json()["detail"]

    def test_webhook_payment_succeeded(self):
        """Test handling payment_intent.succeeded event."""
        event_data = {
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_test123",
                    "status": "succeeded",
                    "metadata": {"user_id": "user-123", "credits": "10"},
                }
            }
        }

        with patch('app.payments.settings') as mock_settings:
            mock_settings.stripe_webhook_secret = "whsec_test"
            mock_settings.stripe_secret_key = "sk_test_xxx"

            with patch('app.payments.stripe') as mock_stripe:
                mock_stripe.Webhook.construct_event.return_value = event_data

                with patch('app.payments.db') as mock_db:
                    mock_db.complete_purchase = AsyncMock(return_value={
                        "status": "completed",
                        "credits_purchased": 10,
                    })

                    from app.payments import router
                    from fastapi import FastAPI
                    from fastapi.testclient import TestClient

                    app = FastAPI()
                    app.include_router(router)
                    client = TestClient(app)

                    response = client.post(
                        "/api/payments/webhook",
                        content=b"{}",
                        headers={"stripe-signature": "test_sig"}
                    )

                    assert response.status_code == 200
                    assert response.json()["status"] == "ok"
                    mock_db.complete_purchase.assert_called_once_with("pi_test123")

    def test_webhook_payment_failed(self):
        """Test handling payment_intent.payment_failed event."""
        event_data = {
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_test123",
                    "status": "failed",
                }
            }
        }

        with patch('app.payments.settings') as mock_settings:
            mock_settings.stripe_webhook_secret = "whsec_test"
            mock_settings.stripe_secret_key = "sk_test_xxx"

            with patch('app.payments.stripe') as mock_stripe:
                mock_stripe.Webhook.construct_event.return_value = event_data

                with patch('app.payments.db') as mock_db:
                    mock_db.fail_purchase = AsyncMock(return_value={"status": "failed"})

                    from app.payments import router
                    from fastapi import FastAPI
                    from fastapi.testclient import TestClient

                    app = FastAPI()
                    app.include_router(router)
                    client = TestClient(app)

                    response = client.post(
                        "/api/payments/webhook",
                        content=b"{}",
                        headers={"stripe-signature": "test_sig"}
                    )

                    assert response.status_code == 200
                    mock_db.fail_purchase.assert_called_once_with("pi_test123")


class TestGetOrCreateStripeCustomer:
    """Test get_or_create_stripe_customer helper function."""

    @pytest.mark.asyncio
    async def test_returns_existing_customer(self):
        """Test that existing customer ID is returned."""
        mock_user = {"id": "user-123", "email": "test@example.com"}

        with patch('app.payments.db') as mock_db:
            mock_db.get_stripe_customer_id = AsyncMock(return_value="cus_existing")

            from app.payments import get_or_create_stripe_customer
            result = await get_or_create_stripe_customer(mock_user)

            assert result == "cus_existing"
            mock_db.get_stripe_customer_id.assert_called_once_with("user-123")

    @pytest.mark.asyncio
    async def test_creates_new_customer(self):
        """Test that new customer is created if none exists."""
        mock_user = {
            "id": "user-123",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }

        mock_customer = MagicMock()
        mock_customer.id = "cus_new123"

        with patch('app.payments.db') as mock_db:
            mock_db.get_stripe_customer_id = AsyncMock(return_value=None)
            mock_db.set_stripe_customer_id = AsyncMock(return_value=True)

            with patch('app.payments.stripe') as mock_stripe:
                mock_stripe.Customer.create.return_value = mock_customer

                from app.payments import get_or_create_stripe_customer
                result = await get_or_create_stripe_customer(mock_user)

                assert result == "cus_new123"
                mock_stripe.Customer.create.assert_called_once_with(
                    email="test@example.com",
                    name="Test User",
                    metadata={"workos_user_id": "user-123"},
                )
                mock_db.set_stripe_customer_id.assert_called_once_with("user-123", "cus_new123")


class TestHandlePaymentSucceeded:
    """Test handle_payment_succeeded helper function."""

    @pytest.mark.asyncio
    async def test_completes_purchase(self):
        """Test that successful payment completes purchase."""
        payment_intent = {"id": "pi_test123"}

        with patch('app.payments.db') as mock_db:
            mock_db.complete_purchase = AsyncMock(return_value={
                "status": "completed",
                "credits_purchased": 10,
            })

            from app.payments import handle_payment_succeeded
            await handle_payment_succeeded(payment_intent)

            mock_db.complete_purchase.assert_called_once_with("pi_test123")

    @pytest.mark.asyncio
    async def test_handles_missing_purchase_record(self):
        """Test handling when purchase record is not found."""
        payment_intent = {"id": "pi_test123"}

        with patch('app.payments.db') as mock_db:
            mock_db.complete_purchase = AsyncMock(return_value=None)

            from app.payments import handle_payment_succeeded
            # Should not raise, just log warning
            await handle_payment_succeeded(payment_intent)

            mock_db.complete_purchase.assert_called_once()


class TestHandlePaymentFailed:
    """Test handle_payment_failed helper function."""

    @pytest.mark.asyncio
    async def test_marks_purchase_failed(self):
        """Test that failed payment marks purchase as failed."""
        payment_intent = {"id": "pi_test123"}

        with patch('app.payments.db') as mock_db:
            mock_db.fail_purchase = AsyncMock(return_value={"status": "failed"})

            from app.payments import handle_payment_failed
            await handle_payment_failed(payment_intent)

            mock_db.fail_purchase.assert_called_once_with("pi_test123")

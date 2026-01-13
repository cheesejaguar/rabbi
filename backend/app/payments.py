"""Payments API router for Stripe integration."""

import logging
import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .config import get_settings
from .auth import get_current_user
from . import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/payments", tags=["payments"])

# Credit packages available for purchase
CREDIT_PACKAGES = {
    "credits_10": {"credits": 10, "price_cents": 100, "display_price": "$1.00"},
    "credits_25": {"credits": 25, "price_cents": 200, "display_price": "$2.00"},
}


class CreateIntentRequest(BaseModel):
    """Request body for creating a payment intent."""
    package_id: str


class VerifyPaymentRequest(BaseModel):
    """Request body for verifying a payment."""
    payment_intent_id: str


@router.get("/packages")
async def get_packages():
    """Return available credit packages."""
    return {"packages": CREDIT_PACKAGES}


@router.post("/create-intent")
async def create_payment_intent(request: Request, body: CreateIntentRequest):
    """Create a Stripe PaymentIntent and CustomerSession for the embedded form."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Validate package
    package = CREDIT_PACKAGES.get(body.package_id)
    if not package:
        raise HTTPException(status_code=400, detail="Invalid package")

    # Check Stripe configuration
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payment system not configured")

    # Initialize Stripe
    stripe.api_key = settings.stripe_secret_key

    try:
        # Get or create Stripe customer
        stripe_customer_id = await get_or_create_stripe_customer(user)

        # Create PaymentIntent
        # Card includes Apple Pay and Google Pay on supported devices
        payment_intent = stripe.PaymentIntent.create(
            amount=package["price_cents"],
            currency="usd",
            customer=stripe_customer_id,
            metadata={
                "user_id": user["id"],
                "package_id": body.package_id,
                "credits": str(package["credits"]),
            },
            payment_method_types=["card", "amazon_pay"],
        )

        # Create CustomerSession for embedded form
        customer_session = stripe.CustomerSession.create(
            customer=stripe_customer_id,
            components={"payment_element": {"enabled": True}},
        )

        # Record pending purchase
        await db.create_purchase(
            user_id=user["id"],
            stripe_payment_intent_id=payment_intent.id,
            stripe_customer_id=stripe_customer_id,
            amount_cents=package["price_cents"],
            credits_purchased=package["credits"],
            package_id=body.package_id,
        )

        return {
            "client_secret": payment_intent.client_secret,
            "customer_session_client_secret": customer_session.client_secret,
            "publishable_key": settings.stripe_publishable_key,
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating payment intent: {e}")
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating payment intent: {e}")
        raise HTTPException(status_code=500, detail=f"Payment error: {str(e)}")


@router.post("/verify-and-fulfill")
async def verify_and_fulfill(request: Request, body: VerifyPaymentRequest):
    """Verify payment with Stripe and fulfill if successful.

    This endpoint provides immediate feedback after payment completion,
    complementing webhooks which may be delayed or unavailable in some environments.

    DISABLED in production - use webhooks for production fulfillment.
    """
    # Only allow in non-production environments for security
    if settings.is_production:
        raise HTTPException(status_code=404, detail="Not found")

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payment system not configured")

    stripe.api_key = settings.stripe_secret_key

    try:
        # Retrieve the payment intent from Stripe
        payment_intent = stripe.PaymentIntent.retrieve(body.payment_intent_id)

        # Verify the payment belongs to this user
        if payment_intent.metadata.get("user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="Payment not found")

        # Check if payment succeeded
        if payment_intent.status != "succeeded":
            return {
                "success": False,
                "status": payment_intent.status,
                "message": "Payment has not succeeded yet",
            }

        # Complete the purchase (idempotent - safe to call multiple times)
        result = await db.complete_purchase(body.payment_intent_id)

        if result:
            return {
                "success": True,
                "credits_added": result["credits_purchased"],
                "message": f"Added {result['credits_purchased']} credits to your account",
            }
        else:
            # Purchase record not found - unusual but payment did succeed
            logger.warning(f"No purchase record for verified payment: {body.payment_intent_id}")
            return {
                "success": False,
                "message": "Payment verified but purchase record not found. Please contact support.",
            }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error verifying payment: {e}")
        raise HTTPException(status_code=500, detail=f"Verification error: {str(e)}")
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        raise HTTPException(status_code=500, detail=f"Verification error: {str(e)}")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    stripe.api_key = settings.stripe_secret_key

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        logger.error("Invalid webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    event_type = event["type"]
    event_data = event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        await handle_payment_succeeded(event_data)
    elif event_type == "payment_intent.payment_failed":
        await handle_payment_failed(event_data)
    else:
        logger.debug(f"Unhandled webhook event type: {event_type}")

    return {"status": "ok"}


async def get_or_create_stripe_customer(user: dict) -> str:
    """Get existing or create new Stripe customer for user."""
    # Check if user already has a Stripe customer ID
    existing_customer_id = await db.get_stripe_customer_id(user["id"])
    if existing_customer_id:
        return existing_customer_id

    # Create new Stripe customer
    name_parts = []
    if user.get("first_name"):
        name_parts.append(user["first_name"])
    if user.get("last_name"):
        name_parts.append(user["last_name"])
    name = " ".join(name_parts) if name_parts else None

    customer = stripe.Customer.create(
        email=user.get("email"),
        name=name,
        metadata={"workos_user_id": user["id"]},
    )

    # Store the mapping
    await db.set_stripe_customer_id(user["id"], customer.id)

    return customer.id


async def handle_payment_succeeded(payment_intent: dict):
    """Process successful payment - add credits to user."""
    payment_intent_id = payment_intent["id"]

    logger.info(f"Processing successful payment: {payment_intent_id}")

    # Complete the purchase (adds credits, handles idempotency)
    result = await db.complete_purchase(payment_intent_id)

    if result:
        if result["status"] == "completed":
            logger.info(f"Purchase {payment_intent_id} completed, added {result['credits_purchased']} credits")
        else:
            logger.warning(f"Purchase {payment_intent_id} status: {result['status']}")
    else:
        # Purchase record not found - this could happen if webhook arrives
        # before the create-intent response was processed
        logger.warning(f"No purchase record found for payment intent: {payment_intent_id}")


async def handle_payment_failed(payment_intent: dict):
    """Process failed payment."""
    payment_intent_id = payment_intent["id"]

    logger.info(f"Processing failed payment: {payment_intent_id}")

    result = await db.fail_purchase(payment_intent_id)

    if result:
        logger.info(f"Purchase {payment_intent_id} marked as failed")
    else:
        logger.warning(f"No purchase record found for failed payment: {payment_intent_id}")

"""Stripe payment integration for credit purchases.

Uses the Stripe PaymentIntents API with the embedded Payment Element via
CustomerSessions. This allows the frontend to render a Stripe-hosted payment
form without handling raw card data.

Fulfillment strategy (dual path):
    * **Production (webhook-based)**: The ``/webhook`` endpoint receives
      ``payment_intent.succeeded`` events from Stripe, verifies the
      webhook signature, and idempotently adds credits to the user's
      account. This is the canonical fulfillment path because webhooks
      are guaranteed delivery by Stripe and are not dependent on the
      user's browser session.
    * **Development (verify-and-fulfill)**: The ``/verify-and-fulfill``
      endpoint lets the frontend poll for payment completion and trigger
      credit fulfillment directly. This exists because Stripe webhooks
      require a publicly reachable URL, which is unavailable during local
      development. This endpoint is **disabled in production** for
      security.

Both paths call ``db.complete_purchase()``, which is idempotent -- calling
it multiple times for the same ``payment_intent_id`` safely no-ops after
the first successful fulfillment.
"""

import logging
import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

from .config import get_settings
from .auth import get_current_user
from .dvar_torah import get_current_parsha
from . import database as db

logger = logging.getLogger(__name__)
settings = get_settings()

# Configure Stripe API key once at module load (thread-safe)
if settings.stripe_secret_key:
    stripe.api_key = settings.stripe_secret_key

router = APIRouter(prefix="/api/payments", tags=["payments"])

# Credit packages available for purchase.
# Each key is a package identifier used in API requests; the value describes
# the number of credits granted and the price in USD cents.
#   - "credits_10": 10 chat credits for $1.00
#   - "credits_25": 25 chat credits for $2.00 (better per-credit value)
CREDIT_PACKAGES = {
    "credits_10": {"credits": 10, "price_cents": 100, "display_price": "$1.00"},
    "credits_25": {"credits": 25, "price_cents": 200, "display_price": "$2.00"},
}

# Sponsorship (tzedakah) tiers for dedicating the week's d'var Torah.
# Amounts follow the tradition of giving in multiples of chai (18),
# the numerical value of the Hebrew word for "life".
SPONSORSHIP_TIERS = {
    "chai": {"amount_cents": 1800, "display_price": "$18", "label": "Chai"},
    "double_chai": {"amount_cents": 3600, "display_price": "$36", "label": "Double Chai"},
    "triple_chai": {"amount_cents": 5400, "display_price": "$54", "label": "Triple Chai"},
    "tenfold_chai": {"amount_cents": 18000, "display_price": "$180", "label": "Tenfold Chai"},
}


class CreateIntentRequest(BaseModel):
    """Request body for creating a payment intent.

    Attributes:
        package_id: The identifier of the credit package to purchase
            (must be a key in ``CREDIT_PACKAGES``).
    """
    package_id: str


class VerifyPaymentRequest(BaseModel):
    """Request body for verifying a payment.

    Attributes:
        payment_intent_id: The Stripe PaymentIntent ID to verify
            (e.g., ``"pi_..."``).
    """
    payment_intent_id: str


class CreateSponsorshipRequest(BaseModel):
    """Request body for sponsoring the week's d'var Torah.

    Attributes:
        tier_id: A key in ``SPONSORSHIP_TIERS`` (chai multiples).
        dedication: The public dedication text (e.g. a name), shown
            alongside the d'var Torah once payment completes.
        dedication_type: How the dedication is framed.
    """
    tier_id: str
    dedication: str = Field(..., min_length=2, max_length=200)
    dedication_type: Literal["memory", "honor", "refuah", "gratitude", "general"] = "general"


@router.get("/packages")
async def get_packages():
    """Return the catalog of available credit packages.

    Returns:
        A JSON object with a ``packages`` key mapping package IDs to
        their credit count, price, and display price.
    """
    return {"packages": CREDIT_PACKAGES}


@router.get("/sponsorship-tiers")
async def get_sponsorship_tiers():
    """Return the catalog of d'var Torah sponsorship tiers.

    Returns:
        A JSON object with a ``tiers`` key plus the current parsha the
        sponsorship would apply to (``None`` during holiday weeks).
    """
    parsha = get_current_parsha()
    return {"tiers": SPONSORSHIP_TIERS, "parsha": parsha}


@router.post("/create-sponsorship-intent")
async def create_sponsorship_intent(request: Request, body: CreateSponsorshipRequest):
    """Create a Stripe PaymentIntent for a d'var Torah sponsorship.

    Mirrors ``create_payment_intent`` but records a sponsorship (a
    tzedakah dedication for the current week's parsha) instead of a
    credit purchase. The PaymentIntent carries ``type=sponsorship``
    metadata so webhook fulfillment routes to the sponsorship path.

    Args:
        request: The incoming FastAPI ``Request`` object.
        body: Tier, dedication text, and dedication type.

    Returns:
        A JSON object with ``client_secret``,
        ``customer_session_client_secret``, ``publishable_key``, and the
        ``parsha`` being sponsored.

    Raises:
        HTTPException: 401 if not authenticated, 400 for an invalid tier
            or during holiday weeks with no parsha, 503 if Stripe or the
            database is not configured, 500 on Stripe API errors.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    tier = SPONSORSHIP_TIERS.get(body.tier_id)
    if not tier:
        raise HTTPException(status_code=400, detail="Invalid sponsorship tier")

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payment system not configured")
    if not settings.db_url:
        raise HTTPException(status_code=503, detail="Database not configured")

    parsha = get_current_parsha()
    if not parsha:
        raise HTTPException(
            status_code=400,
            detail="No weekly parsha this week (holiday reading) - sponsorships reopen next week."
        )

    dedication = body.dedication.strip()

    try:
        stripe_customer_id = await get_or_create_stripe_customer(user)

        payment_intent = stripe.PaymentIntent.create(
            amount=tier["amount_cents"],
            currency="usd",
            customer=stripe_customer_id,
            metadata={
                "type": "sponsorship",
                "user_id": user["id"],
                "tier_id": body.tier_id,
                "parsha_name": parsha["parsha_name"],
            },
            payment_method_types=["card", "amazon_pay"],
        )

        customer_session = stripe.CustomerSession.create(
            customer=stripe_customer_id,
            components={"payment_element": {"enabled": True}},
        )

        await db.create_sponsorship(
            user_id=user["id"],
            stripe_payment_intent_id=payment_intent.id,
            amount_cents=tier["amount_cents"],
            dedication=dedication,
            dedication_type=body.dedication_type,
            parsha_name=parsha["parsha_name"],
            hebrew_year=parsha["hebrew_year"],
        )

        return {
            "client_secret": payment_intent.client_secret,
            "customer_session_client_secret": customer_session.client_secret,
            "publishable_key": settings.stripe_publishable_key,
            "parsha": parsha,
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating sponsorship intent: {e}")
        raise HTTPException(status_code=500, detail="Payment processing error. Please try again or contact support.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating sponsorship intent: {e}")
        raise HTTPException(status_code=500, detail="Payment processing error. Please try again or contact support.")


@router.post("/create-intent")
async def create_payment_intent(request: Request, body: CreateIntentRequest):
    """Create a Stripe PaymentIntent and CustomerSession for the embedded form.

    This endpoint:

    1. Validates the requested package ID.
    2. Retrieves or creates a Stripe Customer for the authenticated user.
    3. Creates a ``PaymentIntent`` with the package amount, attaching
       metadata (``user_id``, ``package_id``, ``credits``) for webhook
       fulfillment.
    4. Creates a ``CustomerSession`` to authorize the frontend's embedded
       Payment Element.
    5. Records a pending purchase row in the database.

    Args:
        request: The incoming FastAPI ``Request`` object.
        body: The request body containing the ``package_id``.

    Returns:
        A JSON object with ``client_secret``,
        ``customer_session_client_secret``, and ``publishable_key`` for
        initializing the Stripe embedded Payment Element.

    Raises:
        HTTPException: 401 if not authenticated, 400 if the package is
            invalid, 503 if Stripe is not configured, or 500 on Stripe
            API errors.
    """
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

        # Create CustomerSession for the embedded Payment Element --
        # this authorizes the frontend to render Stripe's payment form
        # on behalf of this customer.
        customer_session = stripe.CustomerSession.create(
            customer=stripe_customer_id,
            components={"payment_element": {"enabled": True}},
        )

        # Record pending purchase in the database so that webhook
        # fulfillment can look it up by payment_intent_id later.
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
        raise HTTPException(status_code=500, detail="Payment processing error. Please try again or contact support.")
    except Exception as e:
        logger.error(f"Error creating payment intent: {e}")
        raise HTTPException(status_code=500, detail="Payment processing error. Please try again or contact support.")


@router.post("/verify-and-fulfill")
async def verify_and_fulfill(request: Request, body: VerifyPaymentRequest):
    """Verify payment with Stripe and fulfill if successful.

    **Development-only fulfillment path.** This endpoint provides immediate
    feedback after payment completion, complementing webhooks which may be
    delayed or unavailable in local development environments (where Stripe
    cannot reach a webhook URL).

    DISABLED in production -- use webhooks for production fulfillment.

    The flow:
    1. Retrieve the ``PaymentIntent`` from Stripe by ID.
    2. Verify that the payment belongs to the requesting user (via metadata).
    3. If the payment status is ``"succeeded"``, call
       ``db.complete_purchase()`` which is idempotent.

    Args:
        request: The incoming FastAPI ``Request`` object.
        body: The request body containing the ``payment_intent_id``.

    Returns:
        A JSON object with ``success``, ``credits_added`` (on success),
        and a ``message`` describing the outcome.

    Raises:
        HTTPException: 404 in production, 401 if not authenticated,
            403 if the payment does not belong to the user, 503 if
            Stripe is not configured, or 500 on Stripe API errors.
    """
    # Only allow in non-production environments for security
    if settings.is_production:
        raise HTTPException(status_code=404, detail="Not found")

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Payment system not configured")

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

        # Sponsorship payments fulfill through the sponsorship path
        if payment_intent.metadata.get("type") == "sponsorship":
            result = await db.complete_sponsorship(body.payment_intent_id)
            if result:
                return {
                    "success": True,
                    "sponsorship": True,
                    "message": f"Thank you! Your dedication for Parashat {result['parsha_name']} is now live.",
                }
            logger.warning(f"No sponsorship record for verified payment: {body.payment_intent_id}")
            return {
                "success": False,
                "message": "Payment verified but sponsorship record not found. Please contact support.",
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

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error verifying payment: {e}")
        raise HTTPException(status_code=500, detail="Payment verification error. Please try again or contact support.")
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        raise HTTPException(status_code=500, detail="Payment verification error. Please try again or contact support.")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle incoming Stripe webhook events.

    This is the **production fulfillment path**. Stripe sends webhook
    events to this endpoint when payment states change. The flow:

    1. **Signature verification**: The raw request body and the
       ``Stripe-Signature`` header are passed to
       ``stripe.Webhook.construct_event()`` along with the webhook
       secret. This cryptographically verifies that the event originated
       from Stripe and has not been tampered with.
    2. **Event dispatch**: Based on ``event["type"]``:
       - ``payment_intent.succeeded``: Triggers idempotent credit
         fulfillment via ``handle_payment_succeeded()``.
       - ``payment_intent.payment_failed``: Marks the purchase as
         failed via ``handle_payment_failed()``.
       - All other event types are logged and acknowledged.
    3. **Idempotent fulfillment**: ``db.complete_purchase()`` uses a
       database-level status check to ensure credits are only added once,
       even if the webhook is delivered multiple times (Stripe retries on
       non-2xx responses).

    Args:
        request: The incoming FastAPI ``Request`` object (raw body is
            read for signature verification).

    Returns:
        ``{"status": "ok"}`` on successful processing.

    Raises:
        HTTPException: 503 if the webhook secret is not configured,
            400 if the signature is missing or invalid, or 400 if the
            payload cannot be parsed.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    try:
        # Verify the webhook signature to ensure the event is authentic.
        # This uses the raw payload bytes and the Stripe-Signature header
        # against the configured webhook secret.
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        logger.error("Invalid webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event based on its type
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
    """Retrieve an existing Stripe Customer or create a new one.

    Checks the database for a previously stored ``stripe_customer_id``
    for this user. If none exists, creates a new Stripe Customer and
    persists the mapping.

    Args:
        user: The authenticated user dictionary containing at least
            ``"id"`` and optionally ``"email"``, ``"first_name"``,
            ``"last_name"``.

    Returns:
        The Stripe Customer ID string (e.g., ``"cus_..."``).
    """
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


def _is_sponsorship(payment_intent: dict) -> bool:
    """Check whether a PaymentIntent belongs to the sponsorship flow."""
    metadata = payment_intent.get("metadata") or {}
    return metadata.get("type") == "sponsorship"


async def handle_payment_succeeded(payment_intent: dict):
    """Process a successful payment (credit purchase or sponsorship).

    Called by the webhook handler when a ``payment_intent.succeeded``
    event is received. Routes on the ``type`` metadata: sponsorships
    are marked completed (making the dedication publicly visible);
    everything else goes through ``db.complete_purchase()`` which adds
    credits. Both paths are idempotent -- if fulfillment already ran
    (e.g., via the ``verify-and-fulfill`` endpoint), this is a safe no-op.

    Args:
        payment_intent: The Stripe PaymentIntent object (as a dict)
            from the webhook event data.
    """
    payment_intent_id = payment_intent["id"]

    logger.info(f"Processing successful payment: {payment_intent_id}")

    if _is_sponsorship(payment_intent):
        result = await db.complete_sponsorship(payment_intent_id)
        if result:
            logger.info(f"Sponsorship {payment_intent_id} completed for Parashat {result['parsha_name']}")
        else:
            logger.warning(f"No sponsorship record found for payment intent: {payment_intent_id}")
        return

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
    """Process a failed payment by updating the purchase/sponsorship record.

    Called by the webhook handler when a
    ``payment_intent.payment_failed`` event is received.

    Args:
        payment_intent: The Stripe PaymentIntent object (as a dict)
            from the webhook event data.
    """
    payment_intent_id = payment_intent["id"]

    logger.info(f"Processing failed payment: {payment_intent_id}")

    if _is_sponsorship(payment_intent):
        result = await db.fail_sponsorship(payment_intent_id)
        if result:
            logger.info(f"Sponsorship {payment_intent_id} marked as failed")
        else:
            logger.warning(f"No sponsorship record found for failed payment: {payment_intent_id}")
        return

    result = await db.fail_purchase(payment_intent_id)

    if result:
        logger.info(f"Purchase {payment_intent_id} marked as failed")
    else:
        logger.warning(f"No purchase record found for failed payment: {payment_intent_id}")

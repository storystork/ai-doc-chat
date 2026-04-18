"""
payments.py – Stripe integration stub.
Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID in your .env to enable real payments.
Without them the app still runs; the upgrade button will show an error message.
"""
import os
from database import Database

FREE_QUERIES_PER_DAY = 10
FREE_UPLOADS_PER_DAY = 5


def create_checkout_session(user_id: int) -> str:
    """Create a Stripe Checkout session and return the URL."""
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    price_id = os.getenv("STRIPE_PRICE_ID", "").strip()
    success_url = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:8501/?payment=success&session_id={CHECKOUT_SESSION_ID}").strip()
    cancel_url = os.getenv("STRIPE_CANCEL_URL", "http://localhost:8501/").strip()

    if not secret_key or not price_id:
        raise RuntimeError(
            "Stripe is not configured. Add STRIPE_SECRET_KEY and STRIPE_PRICE_ID to your .env file."
        )

    import stripe  # type: ignore
    stripe.api_key = secret_key

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": str(user_id)},
    )
    return session.url


def handle_payment_success(db: Database, session_id: str) -> bool:
    """Verify a completed Stripe session and upgrade the user's plan."""
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        return False

    try:
        import stripe  # type: ignore
        stripe.api_key = secret_key
        session = stripe.checkout.Session.retrieve(session_id)
        if session.get("payment_status") == "paid":
            user_id = int(session["metadata"]["user_id"])
            db.set_user_plan(user_id=user_id, plan="paid")
            return True
    except Exception:
        pass
    return False
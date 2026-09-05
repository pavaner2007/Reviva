"""
pipeline/execute.py — Phase 4: Recovery Execution.

Core execution unit for Reviva — processes one PipelineRun record at a time.

Safety guarantees (enforced inside this function, independent of the caller):
  1. guardrail_passed must be exactly True — rejected otherwise.
  2. escalate_to_human_review strategy never creates a Razorpay link.
  3. Already-executed events (razorpay_link_id present) are skipped (idempotency).
  4. Groq failures never block Razorpay execution — deterministic fallbacks used.
  5. Razorpay failures are caught per-event; the batch continues uninterrupted.
  6. Credentials are never logged.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import razorpay  # type: ignore[import-untyped]  # no type stubs; requires setuptools<70
from sqlalchemy.orm import Session

from app.models import AuditLog, LossEvent, PipelineRun

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Strategies that are permitted to execute (create a Razorpay Payment Link)
EXECUTABLE_STRATEGIES: frozenset[str] = frozenset(
    {
        "send_update_payment_method_link",
        "retry_in_48_hours",
        "retry_immediately",
        "resend_checkout_link_now",
    }
)

# Strategies that must NEVER execute, regardless of guardrail state
BLOCKED_STRATEGIES: frozenset[str] = frozenset({"escalate_to_human_review"})

# Deterministic fallback descriptions — used when Groq call fails
_FALLBACK_DESCRIPTIONS: dict[str, str] = {
    "send_update_payment_method_link": "Update your payment method to complete your payment",
    "retry_in_48_hours": "Complete your pending payment using this secure payment link",
    "retry_immediately": "Retry your payment to complete your order",
    "resend_checkout_link_now": "Complete your payment using this checkout link",
}

# Urgency context strings — fed to Groq prompt
_STRATEGY_URGENCY: dict[str, str] = {
    "send_update_payment_method_link": "Card on file is expired or invalid; customer needs to provide a new one",
    "retry_in_48_hours": "Scheduled retry in 48 hours to give the customer time to add funds",
    "retry_immediately": "Network/bank timeout; safe to retry immediately",
    "resend_checkout_link_now": "OTP expired; resend a fresh checkout link now",
}


# ---------------------------------------------------------------------------
# Groq description generator
# ---------------------------------------------------------------------------

def generate_payment_description(event: LossEvent, pipeline_run: PipelineRun) -> str:
    """
    Ask Groq to generate a short, customer-friendly payment link description.

    Falls back to a deterministic template if Groq is unavailable or returns
    bad output.  A Groq failure NEVER blocks Razorpay execution.

    Returns:
        A non-empty string of at most 100 characters.
    """
    strategy: str = pipeline_run.strategy or ""
    fallback: str = _FALLBACK_DESCRIPTIONS.get(strategy, "Complete your payment using this secure link")

    try:
        from groq import Groq  # lazy import

        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            return fallback

        model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
        urgency = _STRATEGY_URGENCY.get(strategy, "")

        prompt = (
            "You generate short payment link descriptions.\n\n"
            "Return exactly one customer-friendly sentence.\n"
            "Maximum 100 characters.\n"
            "Do not include quotes.\n"
            "Do not include markdown.\n"
            "Do not mention AI, internal failures, guardrails, discounts, or system errors.\n\n"
            f"Context:\n"
            f"Root cause: {pipeline_run.root_cause}\n"
            f"Recovery strategy: {strategy}\n"
            f"Urgency: {urgency}\n\n"
            "Return only the payment description."
        )

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0.2,
        )

        raw: str = response.choices[0].message.content or ""

        # ── Validation / sanitisation ─────────────────────────────────────
        text = raw.strip()
        # Remove surrounding quotes
        if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
            text = text[1:-1].strip()
        if not text:
            return fallback
        # Truncate safely
        if len(text) > 100:
            text = text[:100]
        return text

    except Exception:
        # Any Groq error → use deterministic fallback; never bubble up
        return fallback


# ---------------------------------------------------------------------------
# Razorpay Payment Link creator
# ---------------------------------------------------------------------------

def _create_razorpay_payment_link(
    amount_paise: int,
    currency: str,
    description: str,
    reference_id: str,
) -> dict:
    """
    Create a Razorpay Payment Link in test mode.

    Uses the razorpay SDK (which requires pkg_resources / setuptools < 70).
    Credentials are loaded from RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET env vars.

    Args:
        amount_paise:  Amount in paise — already stored correctly, no scaling.
        currency:      e.g. "INR"
        description:   Customer-friendly description (≤ 100 chars).
        reference_id:  Unique reference (order_id from LossEvent).

    Returns:
        The Razorpay API response dict on success.

    Raises:
        RuntimeError: If credentials are missing or the API call fails.
    """
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

    if not key_id or not key_secret:
        raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be configured")

    client = razorpay.Client(auth=(key_id, key_secret))

    payload = {
        "amount": amount_paise,
        "currency": currency,
        "description": description,
        "reference_id": reference_id,
        "notify": {
            "sms": False,
            "email": False,
        },
    }

    response = client.payment_link.create(payload)
    return response


# ---------------------------------------------------------------------------
# AuditLog helper
# ---------------------------------------------------------------------------

def _write_audit(db: Session, event_id: int, stage: str, detail: str) -> None:
    """Append an AuditLog entry and flush (caller commits)."""
    entry = AuditLog(event_id=event_id, stage=stage, detail=detail)
    db.add(entry)
    db.flush()


# ---------------------------------------------------------------------------
# Main execution entry point
# ---------------------------------------------------------------------------

def execute_action(
    event: LossEvent,
    pipeline_run: PipelineRun,
    db: Session,
) -> dict:
    """
    Execute recovery for a single guardrail-cleared PipelineRun.

    Safety contract (enforced here, not only at the runner level):
      - Returns {"status": "blocked", ...}  if guardrail_passed is not True.
      - Returns {"status": "rejected", ...} if strategy is escalate_to_human_review.
      - Returns {"status": "skipped",  ...} if razorpay_link_id already set.
      - Returns {"status": "success",  ...} on successful Razorpay link creation.
      - Returns {"status": "failed",   ...} on Razorpay API error; batch continues.

    Args:
        event:        LossEvent ORM instance.
        pipeline_run: PipelineRun ORM instance with guardrail_passed set.
        db:           Active SQLAlchemy session (caller owns lifecycle & commit).

    Returns:
        A dict describing the outcome of execution for this event.
    """

    # ── Gate 1: Guardrail must be explicitly True ─────────────────────────
    if pipeline_run.guardrail_passed is not True:
        return {
            "status": "blocked",
            "event_id": event.id,
            "reason": "guardrail_passed is not True -- execution rejected at safety gate",
        }

    strategy: str = pipeline_run.strategy or ""

    # ── Gate 2: Strategy must not be escalation ───────────────────────────
    if strategy in BLOCKED_STRATEGIES:
        return {
            "status": "rejected",
            "event_id": event.id,
            "strategy": strategy,
            "reason": f"Strategy '{strategy}' is blocked from automated execution",
        }

    # ── Gate 3: Strategy must be in executable set ────────────────────────
    if strategy not in EXECUTABLE_STRATEGIES:
        return {
            "status": "rejected",
            "event_id": event.id,
            "strategy": strategy,
            "reason": f"Unknown or unsupported strategy '{strategy}'",
        }

    # ── Gate 4: Idempotency — skip if already executed ────────────────────
    if pipeline_run.razorpay_link_id:
        _write_audit(
            db,
            event.id,
            stage="execute",
            detail="Already executed, skipping duplicate Payment Link creation",
        )
        db.commit()
        return {
            "status": "skipped",
            "event_id": event.id,
            "strategy": strategy,
            "razorpay_link_id": pipeline_run.razorpay_link_id,
            "razorpay_short_url": pipeline_run.razorpay_short_url,
        }

    # ── Step 5: Generate payment description (Groq with fallback) ─────────
    description = generate_payment_description(event, pipeline_run)

    # ── Step 6: Create Razorpay Payment Link ──────────────────────────────
    try:
        rz_response = _create_razorpay_payment_link(
            amount_paise=event.amount,
            currency="INR",
            description=description,
            reference_id=event.order_id,
        )

        link_id: str = rz_response.get("id", "")
        short_url: str = rz_response.get("short_url", "")

        if not link_id:
            raise RuntimeError(f"Razorpay response missing 'id' field: {rz_response}")

    except Exception as exc:
        # Razorpay call failed — log safely, mark as failed, continue batch
        safe_err = str(exc)
        key_id = os.getenv("RAZORPAY_KEY_ID", "")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
        if key_id:
            safe_err = safe_err.replace(key_id, "***KEY_ID***")
        if key_secret:
            safe_err = safe_err.replace(key_secret, "***KEY_SECRET***")

        pipeline_run.action_taken = "execution_failed"
        db.add(pipeline_run)

        _write_audit(
            db,
            event.id,
            stage="execute",
            detail=(
                f"Execution failed for event_id={event.id}, "
                f"strategy='{strategy}' -- {safe_err}"
            ),
        )
        db.commit()

        return {
            "status": "failed",
            "event_id": event.id,
            "strategy": strategy,
            "error": safe_err,
        }

    # ── Step 7: Store Payment Link details ────────────────────────────────
    now_utc = datetime.now(timezone.utc)

    pipeline_run.razorpay_link_id = link_id
    pipeline_run.razorpay_short_url = short_url
    pipeline_run.action_taken = strategy

    # timing metadata — only retry_in_48_hours gets a scheduled_for timestamp
    if strategy == "retry_in_48_hours":
        pipeline_run.scheduled_for = now_utc + timedelta(hours=48)
    else:
        pipeline_run.scheduled_for = None

    db.add(pipeline_run)

    # ── Step 8: Write AuditLog ────────────────────────────────────────────
    amount_rupees = event.amount / 100
    audit_detail = (
        f"Created Razorpay Payment Link {link_id} for strategy '{strategy}', "
        f"amount \u20b9{amount_rupees:.2f}"
    )
    if pipeline_run.scheduled_for:
        audit_detail += f", scheduled_for={pipeline_run.scheduled_for.isoformat()}"

    _write_audit(db, event.id, stage="execute", detail=audit_detail)

    db.commit()

    # ── Step 9: Return structured success result ──────────────────────────
    result: dict = {
        "status": "success",
        "event_id": event.id,
        "strategy": strategy,
        "razorpay_link_id": link_id,
        "razorpay_short_url": short_url,
        "description_used": description,
    }
    if pipeline_run.scheduled_for:
        result["scheduled_for"] = pipeline_run.scheduled_for.isoformat()

    return result

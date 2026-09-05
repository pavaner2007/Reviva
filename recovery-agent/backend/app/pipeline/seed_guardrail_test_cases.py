"""
pipeline/seed_guardrail_test_cases.py — Additive + idempotent guardrail test data seeder.

Creates dedicated test cases for each of the four guardrail rules so that
every guardrail type has at least one clearly demonstrable blocked event.

All test records use the order_id prefix "TEST_GRD_" for easy identification.
Customer IDs use the prefix "CUST_TEST_" to distinguish them from real seeded data.

Idempotency:
    Checks for existing records by order_id before inserting.
    Safe to call multiple times. TC2 (cooldown) updates its prior-cleared-run
    timestamp to "now - 30 minutes" on each call so the cooldown check always fires.

Test Cases:
    TC1 — max_attempts_exceeded
    TC2 — cooldown_active
    TC3 — amount_exceeds_auto_recovery_ceiling
    TC4 — escalated_not_auto_actionable
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap so this module works when run directly as a script
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(dotenv_path=_BACKEND_DIR / ".env", override=False)

from app.database import create_session, init_db  # noqa: E402
from app.models import AuditLog, LossEvent, PipelineRun  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PREFIX_ORDER = "TEST_GRD_"
PREFIX_CUSTOMER = "CUST_TEST_"

# Identifiers for each test case
TC1_CUSTOMER   = f"{PREFIX_CUSTOMER}MAX"
TC2_CUSTOMER   = f"{PREFIX_CUSTOMER}COOL"
TC3_CUSTOMER   = f"{PREFIX_CUSTOMER}AMT"
TC4_CUSTOMER   = f"{PREFIX_CUSTOMER}ESC"

# The "target" event for each test case — the one that Phase 3 will process
TC1_ORDER_NEW  = f"{PREFIX_ORDER}TC1_TARGET"
TC2_ORDER_NEW  = f"{PREFIX_ORDER}TC2_TARGET"
TC3_ORDER_NEW  = f"{PREFIX_ORDER}TC3_TARGET"
TC4_ORDER_NEW  = f"{PREFIX_ORDER}TC4_TARGET"

# Prior cleared events for TC1 (3 history events) and TC2 (1 recent cleared)
TC1_ORDER_HIST = [f"{PREFIX_ORDER}TC1_HIST_{i}" for i in range(1, 4)]
TC2_ORDER_HIST = f"{PREFIX_ORDER}TC2_HIST_1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_event(
    db,
    order_id: str,
    customer_id: str,
    customer_name: str,
    amount: int,
    failure_code: str,
    subscription_id: str | None = None,
) -> tuple[LossEvent, bool]:
    """Return (event, created). created=True only when a new row was inserted."""
    existing = db.query(LossEvent).filter(LossEvent.order_id == order_id).first()
    if existing:
        return existing, False

    event = LossEvent(
        order_id=order_id,
        customer_id=customer_id,
        customer_name=customer_name,
        amount=amount,
        failure_code=failure_code,
        status="failed",
        subscription_id=subscription_id,
        created_at=_utcnow(),
    )
    db.add(event)
    db.flush()  # get event.id without commit
    return event, True


def _get_or_create_pipeline_run(
    db,
    event_id: int,
    root_cause: str,
    root_cause_method: str = "rule-based",
    strategy: str | None = None,
    guardrail_passed: bool | None = None,
    guardrail_reason: str | None = None,
    timestamp: datetime | None = None,
) -> tuple[PipelineRun, bool]:
    """Return (run, created). created=True only when a new row was inserted."""
    existing = db.query(PipelineRun).filter(PipelineRun.event_id == event_id).first()
    if existing:
        return existing, False

    run = PipelineRun(
        event_id=event_id,
        root_cause=root_cause,
        root_cause_method=root_cause_method,
        strategy=strategy,
        guardrail_passed=guardrail_passed,
        guardrail_reason=guardrail_reason,
        timestamp=timestamp or _utcnow(),
    )
    db.add(run)
    db.flush()
    return run, True


def _write_audit(db, event_id: int, stage: str, detail: str) -> None:
    db.add(AuditLog(event_id=event_id, stage=stage, detail=detail, timestamp=_utcnow()))
    db.flush()


# ---------------------------------------------------------------------------
# TC1 — MAX ATTEMPTS
# ---------------------------------------------------------------------------
def seed_tc1_max_attempts(db) -> dict:
    """
    Customer CUST_TEST_MAX has 3 prior cleared runs.
    One new target event — should fail with max_attempts_exceeded.
    """
    result = {"created": 0, "skipped": 0, "identifiers": []}

    # Create 3 historical events with guardrail_passed = True
    for order_id in TC1_ORDER_HIST:
        event, created = _get_or_create_event(
            db,
            order_id=order_id,
            customer_id=TC1_CUSTOMER,
            customer_name="Test User MaxAttempts",
            amount=99_900,   # ₹999 — within ceiling
            failure_code="card_expired",
        )
        if created:
            _write_audit(db, event.id, "detect", "Loss event detected.")
            _write_audit(db, event.id, "root_cause", "Classified as: Card Expired (method: rule-based)")
            run, run_created = _get_or_create_pipeline_run(
                db,
                event_id=event.id,
                root_cause="Card Expired",
                strategy="send_update_payment_method_link",
                guardrail_passed=True,
                guardrail_reason=None,
                timestamp=_utcnow() - timedelta(hours=48),
            )
            if run_created:
                _write_audit(db, event.id, "strategy", "Root cause 'Card Expired' → strategy 'send_update_payment_method_link'")
                _write_audit(db, event.id, "guardrail", "PASSED — all checks cleared, cleared for execution")
                result["created"] += 1
                result["identifiers"].append(order_id)
            else:
                result["skipped"] += 1
        else:
            result["skipped"] += 1

    # Create the new target event (no PipelineRun yet — Phase 3 will process it)
    target_event, created = _get_or_create_event(
        db,
        order_id=TC1_ORDER_NEW,
        customer_id=TC1_CUSTOMER,
        customer_name="Test User MaxAttempts",
        amount=149_900,  # ₹1,499 — within ceiling
        failure_code="insufficient_funds",
    )
    if created:
        _write_audit(db, target_event.id, "detect", "Loss event detected.")
        _write_audit(db, target_event.id, "root_cause", "Classified as: Insufficient Funds (method: rule-based)")
        # Seed PipelineRun with root_cause only — strategy/guardrail set by Phase 3
        run, run_created = _get_or_create_pipeline_run(
            db,
            event_id=target_event.id,
            root_cause="Insufficient Funds",
        )
        if run_created:
            result["created"] += 1
            result["identifiers"].append(TC1_ORDER_NEW)
        else:
            result["skipped"] += 1
    else:
        result["skipped"] += 1

    db.commit()
    return result


# ---------------------------------------------------------------------------
# TC2 — COOLDOWN
# ---------------------------------------------------------------------------
def seed_tc2_cooldown(db) -> dict:
    """
    Customer CUST_TEST_COOL has a prior cleared run from 30 minutes ago.
    One new target event — should fail with cooldown_active.

    On repeated calls, updates the prior run's timestamp to 30 min ago
    so the cooldown check always fires correctly.
    """
    result = {"created": 0, "skipped": 0, "identifiers": []}

    thirty_min_ago = _utcnow() - timedelta(minutes=30)

    # Historical event — cleared 30 minutes ago
    hist_event, created = _get_or_create_event(
        db,
        order_id=TC2_ORDER_HIST,
        customer_id=TC2_CUSTOMER,
        customer_name="Test User Cooldown",
        amount=99_900,
        failure_code="bank_timeout",
    )
    if created:
        _write_audit(db, hist_event.id, "detect", "Loss event detected.")
        _write_audit(db, hist_event.id, "root_cause", "Classified as: Bank/Network Timeout (method: rule-based)")
        run, run_created = _get_or_create_pipeline_run(
            db,
            event_id=hist_event.id,
            root_cause="Bank/Network Timeout",
            strategy="retry_immediately",
            guardrail_passed=True,
            guardrail_reason=None,
            timestamp=thirty_min_ago,
        )
        if run_created:
            _write_audit(db, hist_event.id, "strategy", "Root cause 'Bank/Network Timeout' → strategy 'retry_immediately'")
            _write_audit(db, hist_event.id, "guardrail", "PASSED — all checks cleared, cleared for execution")
            result["created"] += 1
            result["identifiers"].append(TC2_ORDER_HIST)
        else:
            result["skipped"] += 1
    else:
        # Already exists — update timestamp so cooldown is still active
        existing_run = (
            db.query(PipelineRun)
            .filter(PipelineRun.event_id == hist_event.id)
            .first()
        )
        if existing_run:
            existing_run.timestamp = thirty_min_ago
            db.flush()
        result["skipped"] += 1

    # Target event for TC2
    target_event, created = _get_or_create_event(
        db,
        order_id=TC2_ORDER_NEW,
        customer_id=TC2_CUSTOMER,
        customer_name="Test User Cooldown",
        amount=149_900,
        failure_code="otp_failed",
    )
    if created:
        _write_audit(db, target_event.id, "detect", "Loss event detected.")
        _write_audit(db, target_event.id, "root_cause", "Classified as: OTP Verification Failed (method: rule-based)")
        run, run_created = _get_or_create_pipeline_run(
            db,
            event_id=target_event.id,
            root_cause="OTP Verification Failed",
        )
        if run_created:
            result["created"] += 1
            result["identifiers"].append(TC2_ORDER_NEW)
        else:
            result["skipped"] += 1
    else:
        result["skipped"] += 1

    db.commit()
    return result


# ---------------------------------------------------------------------------
# TC3 — AMOUNT CEILING
# ---------------------------------------------------------------------------
def seed_tc3_amount_ceiling(db) -> dict:
    """
    Amount is 600000 paise (₹6,000) — above the ₹4,500 ceiling.
    Uses bank_timeout (normally maps to retry_immediately — an auto strategy),
    so the only reason it's blocked is the amount ceiling.
    """
    result = {"created": 0, "skipped": 0, "identifiers": []}

    target_event, created = _get_or_create_event(
        db,
        order_id=TC3_ORDER_NEW,
        customer_id=TC3_CUSTOMER,
        customer_name="Test User AmountCeiling",
        amount=600_000,   # ₹6,000 — exceeds the ₹4,500 ceiling
        failure_code="bank_timeout",
    )
    if created:
        _write_audit(db, target_event.id, "detect", "Loss event detected.")
        _write_audit(db, target_event.id, "root_cause", "Classified as: Bank/Network Timeout (method: rule-based)")
        run, run_created = _get_or_create_pipeline_run(
            db,
            event_id=target_event.id,
            root_cause="Bank/Network Timeout",
        )
        if run_created:
            result["created"] += 1
            result["identifiers"].append(TC3_ORDER_NEW)
        else:
            result["skipped"] += 1
    else:
        result["skipped"] += 1

    db.commit()
    return result


# ---------------------------------------------------------------------------
# TC4 — ESCALATION
# ---------------------------------------------------------------------------
def seed_tc4_escalation(db) -> dict:
    """
    Uses issuer_declined → root_cause = 'Issuer Declined Transaction'
    → strategy = 'escalate_to_human_review' → always blocked.
    Amount is within the ceiling so only the escalation guardrail fires.
    """
    result = {"created": 0, "skipped": 0, "identifiers": []}

    target_event, created = _get_or_create_event(
        db,
        order_id=TC4_ORDER_NEW,
        customer_id=TC4_CUSTOMER,
        customer_name="Test User Escalation",
        amount=199_900,   # ₹1,999 — within ceiling
        failure_code="issuer_declined",
    )
    if created:
        _write_audit(db, target_event.id, "detect", "Loss event detected.")
        _write_audit(db, target_event.id, "root_cause", "Classified as: Issuer Declined Transaction (method: rule-based)")
        run, run_created = _get_or_create_pipeline_run(
            db,
            event_id=target_event.id,
            root_cause="Issuer Declined Transaction",
        )
        if run_created:
            result["created"] += 1
            result["identifiers"].append(TC4_ORDER_NEW)
        else:
            result["skipped"] += 1
    else:
        result["skipped"] += 1

    db.commit()
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def seed_all(db) -> dict:
    """
    Run all four test case seeders and aggregate results.

    Returns a summary with total created, total skipped, and identifiers.
    """
    tc1 = seed_tc1_max_attempts(db)
    tc2 = seed_tc2_cooldown(db)
    tc3 = seed_tc3_amount_ceiling(db)
    tc4 = seed_tc4_escalation(db)

    all_identifiers = (
        tc1["identifiers"]
        + tc2["identifiers"]
        + tc3["identifiers"]
        + tc4["identifiers"]
    )

    return {
        "created_count": tc1["created"] + tc2["created"] + tc3["created"] + tc4["created"],
        "skipped_existing_count": tc1["skipped"] + tc2["skipped"] + tc3["skipped"] + tc4["skipped"],
        "created_test_case_identifiers": all_identifiers,
        "tc1_max_attempts": tc1,
        "tc2_cooldown": tc2,
        "tc3_amount_ceiling": tc3,
        "tc4_escalation": tc4,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    init_db()
    db = create_session()
    try:
        result = seed_all(db)
        print(json.dumps(result, indent=2))
    finally:
        db.close()

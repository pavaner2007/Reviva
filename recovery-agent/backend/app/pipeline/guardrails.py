from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models import AuditLog, LossEvent, PipelineRun


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_CLEARED_ATTEMPTS: int = 3
AMOUNT_CEILING_PAISE: int = 450_000  # ₹4,500

ESCALATION_STRATEGY = "escalate_to_human_review"

# Fail reason codes (deterministic, snake_case)
REASON_MAX_ATTEMPTS = "max_attempts_exceeded"
REASON_COOLDOWN = "cooldown_active"
REASON_ESCALATION = "escalated_not_auto_actionable"
REASON_AMOUNT_CEILING = "amount_exceeds_auto_recovery_ceiling"


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------
class GuardrailResult(TypedDict):
    passed: bool
    failed_reasons: list[str]


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------
def _write_audit(db: Session, event_id: int, detail: str) -> None:
    """Append a single guardrail-stage AuditLog row and flush."""
    db.add(
        AuditLog(
            event_id=event_id,
            stage="guardrail",
            detail=detail,
            timestamp=datetime.now(timezone.utc),
        )
    )
    db.flush()


def _get_cooldown_hours() -> int:
    """Read GUARDRAIL_COOLDOWN_HOURS from env; default to 12."""
    try:
        return int(os.getenv("GUARDRAIL_COOLDOWN_HOURS", "12"))
    except (ValueError, TypeError):
        return 12


def check_max_attempts(
    pipeline_run: PipelineRun,
    db: Session,
) -> bool:
    """
    PASS if the customer has fewer than MAX_CLEARED_ATTEMPTS (3) previous
    PipelineRun rows where guardrail_passed == True.

    The current pipeline_run is excluded from the count.

    Returns True (PASS) or False (FAIL).
    """
    # We need the customer_id from the parent LossEvent
    event: LossEvent | None = pipeline_run.event
    if event is None:
        # Defensive: cannot check without event; block
        return False

    # Count other cleared runs for the same customer
    cleared_count: int = (
        db.query(PipelineRun)
        .join(LossEvent, PipelineRun.event_id == LossEvent.id)
        .filter(
            LossEvent.customer_id == event.customer_id,
            PipelineRun.guardrail_passed.is_(True),
            PipelineRun.id != pipeline_run.id,  # exclude current
        )
        .count()
    )

    return cleared_count < MAX_CLEARED_ATTEMPTS


def check_cooldown(
    pipeline_run: PipelineRun,
    db: Session,
) -> bool:
    """
    PASS if no previous cleared PipelineRun for the same customer exists
    within the configured cooldown window.

    Uses timezone-aware datetime comparison.

    Returns True (PASS) or False (FAIL).
    """
    event: LossEvent | None = pipeline_run.event
    if event is None:
        return False

    cooldown_hours = _get_cooldown_hours()
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=cooldown_hours)

    # Find the most recent cleared run for this customer (excluding current)
    recent_cleared: PipelineRun | None = (
        db.query(PipelineRun)
        .join(LossEvent, PipelineRun.event_id == LossEvent.id)
        .filter(
            LossEvent.customer_id == event.customer_id,
            PipelineRun.guardrail_passed.is_(True),
            PipelineRun.id != pipeline_run.id,
        )
        .order_by(PipelineRun.timestamp.desc())
        .first()
    )

    if recent_cleared is None:
        return True  # No prior cleared run — pass

    prev_ts = recent_cleared.timestamp
    # Ensure timezone-aware for comparison
    if prev_ts.tzinfo is None:
        prev_ts = prev_ts.replace(tzinfo=timezone.utc)

    # PASS only if the previous cleared run is outside the cooldown window
    return prev_ts < cutoff


def check_escalation(pipeline_run: PipelineRun) -> bool:
    """
    FAIL if the strategy is escalate_to_human_review.
    These must never be auto-cleared.

    Returns True (PASS) or False (FAIL).
    """
    return pipeline_run.strategy != ESCALATION_STRATEGY


def check_amount_ceiling(event: LossEvent) -> bool:
    """
    FAIL if the event amount exceeds AMOUNT_CEILING_PAISE (450000 paise / ₹4,500).

    Returns True (PASS) or False (FAIL).
    """
    return event.amount <= AMOUNT_CEILING_PAISE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_guardrails(
    event: LossEvent,
    pipeline_run: PipelineRun,
    db: Session,
) -> GuardrailResult:
    """
    Run all four guardrail checks and persist the result.

    ALL four checks are always evaluated — no short-circuiting.
    All failed reasons are collected into a deterministic comma-separated list.

    Writes:
        PipelineRun.guardrail_passed  (bool)
        PipelineRun.guardrail_reason  (str | None)
        AuditLog row at stage="guardrail"

    Args:
        event:        The parent LossEvent ORM instance.
        pipeline_run: The current PipelineRun ORM instance (must have strategy set).
        db:           An active SQLAlchemy session.

    Returns:
        GuardrailResult with passed flag and list of failed reasons.
    """
    failed_reasons: list[str] = []

    # ── Check 1: Max Attempts ────────────────────────────────────────────────
    if not check_max_attempts(pipeline_run, db):
        failed_reasons.append(REASON_MAX_ATTEMPTS)

    # ── Check 2: Cooldown ────────────────────────────────────────────────────
    if not check_cooldown(pipeline_run, db):
        failed_reasons.append(REASON_COOLDOWN)

    # ── Check 3: Escalation ──────────────────────────────────────────────────
    if not check_escalation(pipeline_run):
        failed_reasons.append(REASON_ESCALATION)

    # ── Check 4: Amount Ceiling ──────────────────────────────────────────────
    if not check_amount_ceiling(event):
        failed_reasons.append(REASON_AMOUNT_CEILING)

    # ── Final decision ───────────────────────────────────────────────────────
    passed = len(failed_reasons) == 0

    if passed:
        pipeline_run.guardrail_passed = True
        pipeline_run.guardrail_reason = None
        audit_detail = "PASSED \u2014 all checks cleared, cleared for execution"
    else:
        # Deterministic ordering: always the same order as the checks above
        reason_str = ",".join(failed_reasons)
        pipeline_run.guardrail_passed = False
        pipeline_run.guardrail_reason = reason_str
        audit_detail = f"BLOCKED \u2014 reasons: {reason_str}"

    _write_audit(db, event.id, audit_detail)
    db.commit()

    return GuardrailResult(passed=passed, failed_reasons=failed_reasons)


"""
pipeline/guardrails.py — Guardrail checks stage (Phase 3, Step 2).

check_guardrails(event, pipeline_run, db) -> dict

Evaluates ALL four guardrail rules against the current event and pipeline run.
All rules are always checked — no short-circuiting on first failure.
All failing reasons are collected and returned together.

Guardrail Rules:
    1. check_max_attempts()   — customer cannot have > 3 prior cleared attempts
    2. check_cooldown()       — no auto-recovery within GUARDRAIL_COOLDOWN_HOURS
    3. check_escalation()     — escalate_to_human_review is always blocked
    4. check_amount_ceiling() — amount > 450000 paise (₹4,500) is blocked

Final decision written to:
    PipelineRun.guardrail_passed  (bool)
    PipelineRun.guardrail_reason  (str | None — comma-separated fail reasons)

One AuditLog row is written at stage="guardrail" describing PASSED or BLOCKED.
"""

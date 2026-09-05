"""
pipeline/measure.py — Phase 5: Payment outcome measurement & recovery analytics.

Public API:
    check_payment_status(event, pipeline_run, db)  → dict
    get_recovery_summary(db)                        → dict

Design constraints:
    - Never creates a new PipelineRun; only updates the existing one.
    - Never overwrites outcome="recovered" if a Razorpay API call fails.
    - Always fetches fresh Razorpay status — never skips based on existing outcome.
    - All monetary values are integers in paise; no floats stored.
    - Never logs API keys or Razorpay secrets.
    - get_recovery_summary() is always computed live from DB state, never from AuditLog.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Root cause categories (all six must appear in by_root_cause even if zero)
# ---------------------------------------------------------------------------
_ALL_ROOT_CAUSES = [
    "Card Expired",
    "Insufficient Funds",
    "Bank/Network Timeout",
    "OTP Verification Failed",
    "Issuer Declined Transaction",
    "Unclassified — Needs Review",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Razorpay client factory (lazy, so import failure is surfaced at call time)
# ---------------------------------------------------------------------------
def _razorpay_client():
    """Return a Razorpay client built from environment variables."""
    import razorpay  # type: ignore[import-untyped]

    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RuntimeError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in .env"
        )
    return razorpay.Client(auth=(key_id, key_secret))


# ---------------------------------------------------------------------------
# Status → outcome mapping
# ---------------------------------------------------------------------------
_STATUS_MAP: dict[str, str] = {
    "paid":      "recovered",
    "cancelled": "not_recovered",
    "expired":   "not_recovered",
    "created":   "pending",
}


# ---------------------------------------------------------------------------
# check_payment_status
# ---------------------------------------------------------------------------
def check_payment_status(event, pipeline_run, db) -> dict[str, Any]:
    """
    Fetch the latest Razorpay Payment Link status for pipeline_run and update
    its outcome, recovered_amount, and updated_at.

    Args:
        event:        LossEvent ORM instance (parent of pipeline_run).
        pipeline_run: PipelineRun ORM instance to update.
        db:           Active SQLAlchemy session (caller owns lifecycle).

    Returns:
        dict with keys: status, outcome, recovered_amount, razorpay_status,
                         razorpay_link_id, event_id, [error], [preserved].
    """
    from app.models import AuditLog

    link_id: str | None = pipeline_run.razorpay_link_id

    # ── Guard: no link ID — skip ──────────────────────────────────────────
    if not link_id or not link_id.strip():
        warning = (
            f"event_id={event.id}: PipelineRun id={pipeline_run.id} has no "
            f"razorpay_link_id — skipping measurement."
        )
        db.add(AuditLog(
            event_id=event.id,
            stage="measure",
            detail=warning,
        ))
        db.commit()
        return {
            "status":          "skipped",
            "event_id":        event.id,
            "razorpay_link_id": None,
            "detail":          "No razorpay_link_id — skipped.",
        }

    # ── Fetch Razorpay Payment Link status ────────────────────────────────
    razorpay_response: dict | None = None
    fetch_error: str | None = None

    try:
        client = _razorpay_client()
        razorpay_response = client.payment_link.fetch(link_id)
    except Exception as exc:
        # Sanitise: never leak key_id or key_secret in logs
        key_id = os.getenv("RAZORPAY_KEY_ID", "")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
        safe_msg = str(exc)
        if key_id and key_id in safe_msg:
            safe_msg = safe_msg.replace(key_id, "***KEY_ID***")
        if key_secret and key_secret in safe_msg:
            safe_msg = safe_msg.replace(key_secret, "***KEY_SECRET***")
        fetch_error = safe_msg

    # ── Handle API failure ────────────────────────────────────────────────
    if fetch_error is not None:
        previously_recovered = pipeline_run.outcome == "recovered"

        if previously_recovered:
            # CRITICAL: never downgrade a confirmed recovery on API failure
            detail = (
                f"Checked link {link_id}: Razorpay API call failed "
                f"({fetch_error}). Previous confirmed outcome='recovered' "
                f"(recovered_amount={pipeline_run.recovered_amount} paise) "
                f"was PRESERVED — not overwritten."
            )
            db.add(AuditLog(event_id=event.id, stage="measure", detail=detail))
            db.commit()
            return {
                "status":           "measurement_failed",
                "preserved":        True,
                "event_id":         event.id,
                "razorpay_link_id": link_id,
                "outcome":          pipeline_run.outcome,
                "recovered_amount": pipeline_run.recovered_amount,
                "error":            fetch_error,
            }
        else:
            detail = (
                f"Checked link {link_id}: Razorpay API call failed "
                f"({fetch_error}). No prior confirmed recovery — outcome "
                f"left unchanged (currently: {pipeline_run.outcome!r})."
            )
            db.add(AuditLog(event_id=event.id, stage="measure", detail=detail))
            db.commit()
            return {
                "status":           "measurement_failed",
                "preserved":        False,
                "event_id":         event.id,
                "razorpay_link_id": link_id,
                "outcome":          pipeline_run.outcome,
                "error":            fetch_error,
            }

    # ── Map Razorpay status → outcome ─────────────────────────────────────
    raw_status: str = str(razorpay_response.get("status", "")).lower()
    outcome: str = _STATUS_MAP.get(raw_status, "pending")
    recovered_amount: int = 0
    unknown_status_note: str = ""

    if raw_status not in _STATUS_MAP:
        unknown_status_note = (
            f"Unknown Razorpay Payment Link status received: '{raw_status}'. "
            f"Marked as pending."
        )

    if outcome == "recovered":
        # Prefer the actual paid amount from Razorpay; fall back to event.amount
        rzp_amount = razorpay_response.get("amount_paid")
        if isinstance(rzp_amount, int) and rzp_amount > 0:
            recovered_amount = rzp_amount
        else:
            # amount_paid may be 0 or absent — use original event amount
            recovered_amount = event.amount

    # ── Update PipelineRun ────────────────────────────────────────────────
    pipeline_run.outcome = outcome
    pipeline_run.recovered_amount = recovered_amount
    pipeline_run.updated_at = _utcnow()

    # ── Write audit log ───────────────────────────────────────────────────
    rupees = recovered_amount / 100  # paise → rupees for readability
    detail_parts = [
        f"Checked link {link_id}: Razorpay status='{raw_status}' "
        f"→ outcome='{outcome}', recovered_amount=₹{rupees:.2f}"
    ]
    if unknown_status_note:
        detail_parts.append(unknown_status_note)

    db.add(AuditLog(
        event_id=event.id,
        stage="measure",
        detail=" | ".join(detail_parts),
    ))
    db.commit()

    return {
        "status":           "measured",
        "event_id":         event.id,
        "razorpay_link_id": link_id,
        "razorpay_status":  raw_status,
        "outcome":          outcome,
        "recovered_amount": recovered_amount,
        "updated_at":       pipeline_run.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# get_recovery_summary
# ---------------------------------------------------------------------------
def get_recovery_summary(db) -> dict[str, Any]:
    """
    Compute and return a live recovery analytics summary from the current
    database state.

    Never hardcodes values. Never reads from AuditLog for financial totals.
    Always queries PipelineRun and LossEvent directly.

    Returns:
        dict with all 8 required metrics.
    """
    from app.models import LossEvent, PipelineRun

    # Load all pipeline runs with their parent events in one query
    all_runs: list[PipelineRun] = (
        db.query(PipelineRun).order_by(PipelineRun.event_id.asc()).all()
    )

    # ── Pre-compute sets/accumulators ─────────────────────────────────────
    total_executed_events = 0
    total_at_risk_amount = 0
    eligible_at_risk_amount = 0
    total_recovered_amount = 0

    recovered_count = 0
    pending_count = 0
    not_recovered_count = 0

    guardrail_blocked_value = 0

    # by_root_cause — initialise all 6 categories to zero
    by_root_cause: dict[str, dict[str, int]] = {
        rc: {"attempted_count": 0, "recovered_count": 0, "recovered_amount": 0}
        for rc in _ALL_ROOT_CAUSES
    }

    for run in all_runs:
        event: LossEvent | None = run.event
        event_amount: int = event.amount if event else 0
        root_cause: str = run.root_cause or ""

        has_link = bool(run.razorpay_link_id and run.razorpay_link_id.strip())

        # ── METRIC 1 & 2: executed events + at-risk amount ────────────────
        if has_link:
            total_executed_events += 1
            total_at_risk_amount += event_amount

        # ── METRIC 3: eligible at-risk (guardrail_passed == True) ─────────
        if run.guardrail_passed is True:
            eligible_at_risk_amount += event_amount

        # ── METRIC 4 & 6: recovered amount + outcome counts ───────────────
        if run.outcome == "recovered":
            total_recovered_amount += (run.recovered_amount or 0)
            recovered_count += 1
        elif run.outcome == "pending":
            pending_count += 1
        elif run.outcome == "not_recovered":
            not_recovered_count += 1

        # ── METRIC 7: guardrail blocked value ────────────────────────────
        if run.guardrail_passed is False:
            guardrail_blocked_value += event_amount

        # ── METRIC 8: by_root_cause breakdown ────────────────────────────
        if root_cause in by_root_cause and has_link:
            by_root_cause[root_cause]["attempted_count"] += 1
            if run.outcome == "recovered":
                by_root_cause[root_cause]["recovered_count"] += 1
                by_root_cause[root_cause]["recovered_amount"] += (
                    run.recovered_amount or 0
                )

    # ── METRIC 5: recovery rate ───────────────────────────────────────────
    if total_at_risk_amount > 0:
        recovery_rate = round(
            (total_recovered_amount / total_at_risk_amount) * 100, 2
        )
    else:
        recovery_rate = 0.0

    return {
        "total_executed_events":    total_executed_events,
        "total_at_risk_amount":     total_at_risk_amount,
        "eligible_at_risk_amount":  eligible_at_risk_amount,
        "total_recovered_amount":   total_recovered_amount,
        "recovery_rate":            recovery_rate,
        "recovered_count":          recovered_count,
        "pending_count":            pending_count,
        "not_recovered_count":      not_recovered_count,
        "guardrail_blocked_value":  guardrail_blocked_value,
        "by_root_cause":            by_root_cause,
    }

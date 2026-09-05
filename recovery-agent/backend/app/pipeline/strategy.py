"""
pipeline/strategy.py — Strategy Selection stage (Phase 3, Step 1).

select_strategy(pipeline_run, db) -> dict

Maps each root_cause category to a deterministic recovery strategy using a
plain Python dictionary. No LLMs, no external APIs, no randomness.

Strategy Mapping:
    Card Expired                  → send_update_payment_method_link
    Insufficient Funds            → retry_in_48_hours
    Bank/Network Timeout          → retry_immediately
    OTP Verification Failed       → resend_checkout_link_now
    Issuer Declined Transaction   → escalate_to_human_review
    Unclassified — Needs Review   → escalate_to_human_review

After selecting:
    1. PipelineRun.strategy is updated in-place.
    2. One AuditLog row is written at stage="strategy".
    3. db.commit() is called.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models import AuditLog, PipelineRun


# ---------------------------------------------------------------------------
# Deterministic strategy map — root_cause → strategy
# ---------------------------------------------------------------------------
STRATEGY_MAP: dict[str, str] = {
    "Card Expired":               "send_update_payment_method_link",
    "Insufficient Funds":         "retry_in_48_hours",
    "Bank/Network Timeout":       "retry_immediately",
    "OTP Verification Failed":    "resend_checkout_link_now",
    "Issuer Declined Transaction": "escalate_to_human_review",
    "Unclassified \u2014 Needs Review": "escalate_to_human_review",
}

# Fallback for any root_cause not in the map (defensive)
_FALLBACK_STRATEGY = "escalate_to_human_review"


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------
class StrategyResult(TypedDict):
    strategy: str
    skipped: bool   # True if already set and not forced


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------
def _write_audit(db: Session, event_id: int, stage: str, detail: str) -> None:
    """Append a single AuditLog row and flush (caller commits)."""
    db.add(
        AuditLog(
            event_id=event_id,
            stage=stage,
            detail=detail,
            timestamp=datetime.now(timezone.utc),
        )
    )
    db.flush()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def select_strategy(
    pipeline_run: PipelineRun,
    db: Session,
    force: bool = False,
) -> StrategyResult:
    """
    Select a recovery strategy based on the pipeline_run's root_cause.

    Args:
        pipeline_run: An existing PipelineRun ORM instance (must have root_cause set).
        db:           An active SQLAlchemy session.
        force:        If True, overwrite an already-selected strategy.

    Returns:
        StrategyResult with strategy and skipped flag.

    Raises:
        ValueError: If pipeline_run.root_cause is None.
    """
    if not pipeline_run.root_cause:
        raise ValueError(
            f"PipelineRun id={pipeline_run.id} has no root_cause — "
            "cannot select strategy. Run Phase 2 first."
        )

    # ── Skip if already selected and not forced ─────────────────────────────
    if pipeline_run.strategy and not force:
        return StrategyResult(strategy=pipeline_run.strategy, skipped=True)

    # ── Deterministic lookup ─────────────────────────────────────────────────
    root_cause = pipeline_run.root_cause
    strategy = STRATEGY_MAP.get(root_cause, _FALLBACK_STRATEGY)

    # ── Persist ──────────────────────────────────────────────────────────────
    pipeline_run.strategy = strategy

    _write_audit(
        db,
        pipeline_run.event_id,
        "strategy",
        f"Root cause '{root_cause}' → strategy '{strategy}'",
    )

    db.commit()

    return StrategyResult(strategy=strategy, skipped=False)

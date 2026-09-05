"""
pipeline/detect.py — Loss detection stage (Phase 2, Step 1).

detect_loss(event, db)

Confirms that a LossEvent is a genuine loss, creates/retrieves the
associated PipelineRun row, and writes an AuditLog entry for the
"detect" stage.

Idempotency:
    If a PipelineRun already exists for the event, it is reused.
    A "detect" AuditLog entry is only written when a new PipelineRun
    is created, not on subsequent calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models import AuditLog, LossEvent, PipelineRun


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------
class DetectResult(TypedDict):
    detected: bool                # True if event.status == "failed"
    pipeline_run_id: int | None   # PipelineRun.id (None if not detected)
    created_new: bool             # True if a new PipelineRun was inserted


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------
def detect_loss(event: LossEvent, db: Session) -> DetectResult:
    """
    Detect whether a LossEvent is a confirmed loss and ensure a
    PipelineRun row exists.

    Args:
        event: The LossEvent ORM instance to evaluate.
        db:    An active SQLAlchemy session.

    Returns:
        DetectResult with detected, pipeline_run_id, and created_new fields.
    """
    # ── Gate: only "failed" events are confirmed loss events ────────────────
    if event.status != "failed":
        return DetectResult(detected=False, pipeline_run_id=None, created_new=False)

    # ── Check for an existing PipelineRun (idempotency) ────────────────────
    existing_run: PipelineRun | None = (
        db.query(PipelineRun)
        .filter(PipelineRun.event_id == event.id)
        .first()
    )

    if existing_run is not None:
        # Already has a pipeline run — nothing to create
        return DetectResult(
            detected=True,
            pipeline_run_id=existing_run.id,
            created_new=False,
        )

    # ── Create a new PipelineRun ────────────────────────────────────────────
    pipeline_run = PipelineRun(
        event_id=event.id,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(pipeline_run)
    db.flush()  # Populates pipeline_run.id without committing the transaction

    # ── Write AuditLog for the detect stage ────────────────────────────────
    audit = AuditLog(
        event_id=event.id,
        stage="detect",
        detail=(
            f"Loss event confirmed: failure_code={event.failure_code}, "
            f"amount={event.amount}"
        ),
        timestamp=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    return DetectResult(
        detected=True,
        pipeline_run_id=pipeline_run.id,
        created_new=True,
    )

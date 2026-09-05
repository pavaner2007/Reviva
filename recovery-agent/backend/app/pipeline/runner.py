"""
pipeline/runner.py — Pipeline orchestrator (Phases 2, 3, and 4).

Phase 2 pipeline:
    detect_loss()  →  analyze_root_cause()

Phase 3 pipeline:
    select_strategy()  →  check_guardrails()

Phase 4 pipeline:
    execute_action()   → Razorpay Payment Link creation for cleared events

All pipelines are idempotent by default.

CLI usage (run from the backend/ directory):
    python -m app.pipeline.runner            # Phase 2 normal run
    python -m app.pipeline.runner --force    # Phase 2 forced reprocessing
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap so this module works when run directly as a script
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env before any app imports
from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=_BACKEND_DIR / ".env", override=False)

from app.database import create_session, init_db  # noqa: E402
from app.models import LossEvent, PipelineRun  # noqa: E402
from app.pipeline.detect import detect_loss  # noqa: E402
from app.pipeline.root_cause import analyze_root_cause  # noqa: E402
from app.pipeline.strategy import select_strategy  # noqa: E402
from app.pipeline.guardrails import check_guardrails  # noqa: E402


# ---------------------------------------------------------------------------
# Summary type (plain dict for easy JSON serialisation)
# ---------------------------------------------------------------------------
def _empty_summary() -> dict:
    return {
        "total_processed": 0,
        "rule_based_count": 0,
        "llm_fallback_count": 0,
        "unclassified_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_pipeline_phase2(db, force: bool = False) -> dict:
    """
    Run the Phase 2 detection + root-cause pipeline over all LossEvents.

    Args:
        db:    An active SQLAlchemy session (caller owns lifecycle).
        force: If True, reclassify already-classified events.

    Returns:
        Summary dict with counts per classification method.
    """
    events: list[LossEvent] = (
        db.query(LossEvent).order_by(LossEvent.id.asc()).all()
    )

    summary = _empty_summary()
    summary["total_processed"] = len(events)

    for event in events:
        try:
            # Step 1 — Loss detection
            detect_result = detect_loss(event, db)

            if not detect_result["detected"]:
                # Non-failed events are not loss events; skip silently
                summary["total_processed"] -= 1
                continue

            # Step 2 — Root cause analysis
            rc_result = analyze_root_cause(event, db, force=force)

            if rc_result["skipped"]:
                summary["skipped_count"] += 1
                continue

            method = rc_result["root_cause_method"]
            if method == "rule-based":
                summary["rule_based_count"] += 1
            elif method == "llm-fallback":
                summary["llm_fallback_count"] += 1
            else:
                summary["unclassified_count"] += 1

        except Exception as exc:
            # One bad event must never block the rest
            summary["failed_count"] += 1
            print(
                f"[ERROR] Pipeline failed for event_id={event.id}: {exc}",
                file=sys.stderr,
            )

    return summary


# ---------------------------------------------------------------------------
# Phase 3 summary type
# ---------------------------------------------------------------------------
def _empty_phase3_summary() -> dict:
    return {
        "total_processed": 0,
        "guardrail_passed_count": 0,
        "guardrail_blocked_count": 0,
        "blocked_reasons_breakdown": {
            "max_attempts_exceeded": 0,
            "cooldown_active": 0,
            "escalated_not_auto_actionable": 0,
            "amount_exceeds_auto_recovery_ceiling": 0,
        },
        "skipped_count": 0,
        "failed_count": 0,
    }


# ---------------------------------------------------------------------------
# Phase 3 Orchestrator
# ---------------------------------------------------------------------------
def run_pipeline_phase3(db, force: bool = False) -> dict:
    """
    Run the Phase 3 strategy selection + guardrail pipeline.

    Processes all PipelineRun records that have a non-null root_cause.
    Skips records where strategy is already set (unless force=True).

    Args:
        db:    An active SQLAlchemy session (caller owns lifecycle).
        force: If True, reprocess already-processed records.

    Returns:
        Summary dict with guardrail pass/block counts and reason breakdown.
    """
    from app.models import LossEvent  # local to avoid circular import concerns

    runs: list[PipelineRun] = (
        db.query(PipelineRun)
        .filter(PipelineRun.root_cause.isnot(None))
        .order_by(PipelineRun.event_id.asc())
        .all()
    )

    summary = _empty_phase3_summary()

    for run in runs:
        try:
            # Skip if no root_cause (defensive guard)
            if not run.root_cause:
                print(
                    f"[WARN] PipelineRun id={run.id} has no root_cause — skipping.",
                    file=sys.stderr,
                )
                continue

            # Skip if already processed and not forced
            if run.strategy is not None and not force:
                summary["skipped_count"] += 1
                continue

            # Load the parent LossEvent
            event: LossEvent | None = run.event
            if event is None:
                print(
                    f"[WARN] PipelineRun id={run.id} has no associated LossEvent — skipping.",
                    file=sys.stderr,
                )
                summary["failed_count"] += 1
                continue

            # ── Step 1: Strategy selection ───────────────────────────────────
            select_strategy(run, db, force=force)

            # ── Step 2: Guardrail checks ─────────────────────────────────────
            guardrail_result = check_guardrails(event, run, db)

            # ── Aggregate summary ────────────────────────────────────────────
            summary["total_processed"] += 1

            if guardrail_result["passed"]:
                summary["guardrail_passed_count"] += 1
            else:
                summary["guardrail_blocked_count"] += 1
                breakdown = summary["blocked_reasons_breakdown"]
                for reason in guardrail_result["failed_reasons"]:
                    if reason in breakdown:
                        breakdown[reason] += 1

        except Exception as exc:
            summary["failed_count"] += 1
            print(
                f"[ERROR] Phase 3 pipeline failed for PipelineRun id={run.id}: {exc}",
                file=sys.stderr,
            )

    return summary

# ---------------------------------------------------------------------------
# Phase 4 summary type
# ---------------------------------------------------------------------------
def _empty_phase4_summary() -> dict:
    return {
        "total_eligible": 0,
        "successfully_executed": 0,
        "failed_executions": 0,
        "skipped_already_executed": 0,
        "blocked_rejected": 0,
    }


# ---------------------------------------------------------------------------
# Phase 4 Orchestrator
# ---------------------------------------------------------------------------
def run_pipeline_phase4(db) -> dict:
    """
    Run the Phase 4 recovery execution pipeline.

    Fetches all PipelineRun records with guardrail_passed == True that have
    not yet been executed (razorpay_link_id is None) and calls execute_action()
    for each one.  A 0.5 s rate-limit delay is applied between consecutive
    actual Razorpay API calls.  Individual failures do not abort the batch.

    Args:
        db: An active SQLAlchemy session (caller owns lifecycle).

    Returns:
        Summary dict with execution outcome counts.
    """
    import time
    from app.pipeline.execute import execute_action

    # Fetch all guardrail-cleared runs, ordered for deterministic processing
    all_cleared: list[PipelineRun] = (
        db.query(PipelineRun)
        .filter(PipelineRun.guardrail_passed.is_(True))
        .order_by(PipelineRun.event_id.asc())
        .all()
    )

    summary = _empty_phase4_summary()
    summary["total_eligible"] = len(all_cleared)

    made_real_api_call = False  # track to apply rate-limit delay correctly

    for run in all_cleared:
        try:
            event: LossEvent | None = run.event
            if event is None:
                print(
                    f"[WARN] PipelineRun id={run.id} has no associated LossEvent — skipping.",
                    file=sys.stderr,
                )
                summary["blocked_rejected"] += 1
                continue

            # Idempotency: skip already-executed runs without sleeping
            if run.razorpay_link_id is not None:
                summary["skipped_already_executed"] += 1
                continue

            # Rate-limit: pause between actual API calls only
            if made_real_api_call:
                time.sleep(1.5)

            result = execute_action(event, run, db)
            made_real_api_call = True  # execute_action attempted (or failed) an API call

            status = result.get("status")
            if status == "success":
                summary["successfully_executed"] += 1
            elif status == "skipped":
                # Idempotency detected inside execute_action (race condition guard)
                summary["skipped_already_executed"] += 1
                made_real_api_call = False  # no actual API call was made
            elif status in ("blocked", "rejected"):
                summary["blocked_rejected"] += 1
                made_real_api_call = False
            else:  # "failed"
                summary["failed_executions"] += 1

        except Exception as exc:
            summary["failed_executions"] += 1
            print(
                f"[ERROR] Phase 4 pipeline failed for PipelineRun id={run.id}: {exc}",
                file=sys.stderr,
            )

    return summary



def _cli() -> None:
    """Command-line interface for running the Phase 2 pipeline."""
    force = "--force" in sys.argv

    init_db()
    db = create_session()
    try:
        print(f"\nRunning Phase 2 pipeline (force={force}) ...\n")
        summary = run_pipeline_phase2(db, force=force)

        print("=" * 40)
        print("PHASE 2 PIPELINE COMPLETE")
        print("=" * 40)
        print(f"  Total processed   : {summary['total_processed']}")
        print(f"  Rule-based        : {summary['rule_based_count']}")
        print(f"  LLM fallback      : {summary['llm_fallback_count']}")
        print(f"  Unclassified      : {summary['unclassified_count']}")
        print(f"  Skipped (cached)  : {summary['skipped_count']}")
        print(f"  Failed (errors)   : {summary['failed_count']}")
        print("=" * 40)
    finally:
        db.close()


if __name__ == "__main__":
    _cli()

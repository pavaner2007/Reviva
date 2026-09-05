"""
pipeline/runner.py — Phase 2 pipeline orchestrator.

Fetches all LossEvent records and runs the Phase 2 pipeline on each:
    detect_loss()  →  analyze_root_cause()

Returns a summary dict with per-method counts.

CLI usage (run from the backend/ directory):
    python -m app.pipeline.runner            # normal run
    python -m app.pipeline.runner --force    # forced reprocessing
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
from app.models import LossEvent  # noqa: E402
from app.pipeline.detect import detect_loss  # noqa: E402
from app.pipeline.root_cause import analyze_root_cause  # noqa: E402


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
# CLI entry point
# ---------------------------------------------------------------------------
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

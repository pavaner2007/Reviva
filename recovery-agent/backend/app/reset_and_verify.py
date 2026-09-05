"""
backend/app/reset_and_verify.py — Phase 7 end-to-end pipeline verification script.

Resets the LOCAL SQLite database and runs all 5 pipeline phases in sequence,
printing a clear status report at every step and a final summary at the end.

Usage (run from the backend/ directory):
    python -m app.reset_and_verify           # interactive — prompts for confirmation
    python -m app.reset_and_verify --yes     # skips confirmation prompt

IMPORTANT:
    This script resets the LOCAL database only.
    Razorpay test-mode Payment Links already created in the Razorpay dashboard
    will NOT be deleted or cancelled. They are external resources.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — works whether run as `python -m app.reset_and_verify`
# or `python app/reset_and_verify.py`
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(dotenv_path=_BACKEND_DIR / ".env", override=False)

from app.database import create_session, init_db
from app.models import AuditLog, LossEvent, PipelineRun
from app.pipeline.measure import get_recovery_summary


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _sep(char="=", width=50):
    print(char * width)


def _header(title: str):
    _sep()
    print(f"  {title}")
    _sep()


def _ok(msg: str):
    print(f"  [OK]  {msg}")


def _fail(msg: str):
    print(f"  [!!]  {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# STEP 0 — Confirm
# ---------------------------------------------------------------------------
def _confirm(force: bool) -> bool:
    _sep("-")
    print("\n  WARNING: This will delete all local LossEvent, PipelineRun and")
    print("  AuditLog records. Razorpay test-mode Payment Links already created")
    print("  in the Razorpay dashboard will NOT be deleted.\n")
    _sep("-")
    if force:
        print("  --yes flag detected — skipping confirmation.\n")
        return True
    ans = input("  Are you sure? Type YES to continue: ").strip()
    print()
    return ans == "YES"


# ---------------------------------------------------------------------------
# STEP 1 — Clear local data
# ---------------------------------------------------------------------------
def step1_clear(db) -> None:
    _header("STEP 1 — CLEAR LOCAL DATA")
    # Delete in FK-safe order: AuditLog first, then PipelineRun, then LossEvent
    al_count = db.query(AuditLog).delete()
    pr_count = db.query(PipelineRun).delete()
    le_count = db.query(LossEvent).delete()
    db.commit()
    print(f"  Deleted {al_count} AuditLog rows")
    print(f"  Deleted {pr_count} PipelineRun rows")
    print(f"  Deleted {le_count} LossEvent rows")

    # Verify
    assert db.query(LossEvent).count() == 0
    assert db.query(PipelineRun).count() == 0
    assert db.query(AuditLog).count() == 0
    _ok("Database cleared and verified empty.")


# ---------------------------------------------------------------------------
# STEP 2 — Reseed data
# ---------------------------------------------------------------------------
def step2_seed(db) -> dict:
    _header("STEP 2 — RESEED DATA")
    from app.seed_data import seed
    from app.pipeline.seed_guardrail_test_cases import seed_all

    # Seed 50 synthetic events (clear_existing=False because we already cleared)
    seed(clear_existing=False)
    normal_count = db.query(LossEvent).count()
    _ok(f"Seeded {normal_count} synthetic LossEvent records.")

    # Seed guardrail test cases (additive, idempotent)
    result = seed_all(db)
    guardrail_count = sum(r.get("inserted", 0) for r in result.values() if isinstance(r, dict))
    total_count = db.query(LossEvent).count()

    print(f"  Normal events    : {normal_count}")
    print(f"  Guardrail events : {total_count - normal_count}")
    print(f"  Total events     : {total_count}")
    _ok("Seed complete.")
    return {"normal": normal_count, "total": total_count}


# ---------------------------------------------------------------------------
# STEP 3 — Phase 2: Detection + Root Cause
# ---------------------------------------------------------------------------
def step3_phase2(db) -> dict:
    _header("STEP 3 — PHASE 2: Detection + Root Cause Analysis")
    from app.pipeline.runner import run_pipeline_phase2

    summary = run_pipeline_phase2(db, force=False)
    print(f"  Total processed  : {summary['total_processed']}")
    print(f"  Rule-based       : {summary['rule_based_count']}")
    print(f"  LLM fallback     : {summary['llm_fallback_count']}")
    print(f"  Unclassified     : {summary['unclassified_count']}")
    print(f"  Failed (errors)  : {summary['failed_count']}")
    print(f"  Skipped (cached) : {summary['skipped_count']}")

    if summary["failed_count"] > 0:
        _fail(f"Phase 2 had {summary['failed_count']} failures.")
    else:
        _ok("Phase 2 completed without errors.")
    return summary


# ---------------------------------------------------------------------------
# STEP 4 — Phase 3: Strategy + Guardrails
# ---------------------------------------------------------------------------
def step4_phase3(db) -> dict:
    _header("STEP 4 — PHASE 3: Strategy Selection + Guardrail Evaluation")
    from app.pipeline.runner import run_pipeline_phase3

    summary = run_pipeline_phase3(db, force=False)
    print(f"  Total processed  : {summary['total_processed']}")
    print(f"  Guardrail passed : {summary['guardrail_passed_count']}")
    print(f"  Guardrail blocked: {summary['guardrail_blocked_count']}")
    print(f"  Skipped (cached) : {summary['skipped_count']}")
    print(f"  Failed (errors)  : {summary['failed_count']}")
    print("\n  Block reason breakdown:")
    for reason, count in summary.get("blocked_reasons_breakdown", {}).items():
        if count > 0:
            print(f"    {reason}: {count}")

    if summary["failed_count"] > 0:
        _fail(f"Phase 3 had {summary['failed_count']} failures.")
    else:
        _ok("Phase 3 completed without errors.")
    return summary


# ---------------------------------------------------------------------------
# STEP 5 — Phase 4: Recovery Execution
# ---------------------------------------------------------------------------
def step5_phase4(db) -> dict:
    _header("STEP 5 — PHASE 4: Recovery Execution (Razorpay Payment Links)")
    from app.pipeline.runner import run_pipeline_phase4

    try:
        summary = run_pipeline_phase4(db)
    except Exception as exc:
        safe = str(exc)
        for key in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
            import os
            val = os.getenv(key, "")
            if val and val in safe:
                safe = safe.replace(val, f"***{key}***")
        _fail(f"Phase 4 raised an exception: {safe}")
        return {"total_eligible": 0, "successfully_executed": 0,
                "failed_executions": 1, "skipped_already_executed": 0}

    print(f"  Total eligible   : {summary['total_eligible']}")
    print(f"  Executed         : {summary['successfully_executed']}")
    print(f"  Failed           : {summary['failed_executions']}")
    print(f"  Already executed : {summary['skipped_already_executed']}")

    if summary["failed_executions"] > 0:
        print(
            "\n  NOTE: Execution failures are often caused by invalid or missing\n"
            "  Razorpay API credentials. This is expected in offline environments.\n"
            "  The pipeline verification continues."
        )
    else:
        _ok("Phase 4 completed without errors.")
    return summary


# ---------------------------------------------------------------------------
# STEP 6 — Phase 5: Outcome Measurement
# ---------------------------------------------------------------------------
def step6_phase5(db) -> dict:
    _header("STEP 6 — PHASE 5: Payment Outcome Measurement")
    from app.pipeline.runner import run_pipeline_phase5

    summary = run_pipeline_phase5(db)
    print(f"  Total checked    : {summary['total_checked']}")
    print(f"  Recovered        : {summary['recovered_count']}")
    print(f"  Pending          : {summary['pending_count']}")
    print(f"  Not recovered    : {summary['not_recovered_count']}")
    print(f"  Measurement fails: {summary['measurement_failed_count']}")

    if summary["recovered_count"] == 0:
        print(
            "\n  NOTE: 0 recovered events after a fresh reset is EXPECTED.\n"
            "  Freshly created Payment Links are pending until a test payment\n"
            "  is manually completed in the Razorpay test dashboard."
        )
        _ok("Phase 5 completed. No recovered events yet (expected).")
    else:
        _ok(f"Phase 5 completed. {summary['recovered_count']} event(s) recovered!")
    return summary


# ---------------------------------------------------------------------------
# FINAL REPORT
# ---------------------------------------------------------------------------
def final_report(db) -> None:
    _sep()
    print("  FINAL PIPELINE VERIFICATION REPORT")
    _sep()

    analytics = get_recovery_summary(db)

    total_events = db.query(LossEvent).count()
    total_runs = db.query(PipelineRun).count()

    # Root cause breakdown
    from collections import Counter
    runs = db.query(PipelineRun).all()
    root_cause_counts: Counter = Counter(
        r.root_cause for r in runs if r.root_cause
    )

    # Blocked reasons
    blocked_reasons: Counter = Counter()
    for r in runs:
        if r.guardrail_passed is False and r.guardrail_reason:
            for reason in r.guardrail_reason.split(","):
                blocked_reasons[reason.strip()] += 1

    print(f"\n  Total LossEvents          : {total_events}")
    print(f"  Total PipelineRuns        : {total_runs}")

    print("\n  Root Cause Breakdown:")
    for rc, count in sorted(root_cause_counts.items(), key=lambda x: -x[1]):
        print(f"    {rc}: {count}")

    guardrail_passed = sum(1 for r in runs if r.guardrail_passed is True)
    guardrail_blocked = sum(1 for r in runs if r.guardrail_passed is False)
    print(f"\n  Guardrail Passed          : {guardrail_passed}")
    print(f"  Guardrail Blocked         : {guardrail_blocked}")

    if blocked_reasons:
        print("\n  Block Reason Breakdown:")
        for reason, count in blocked_reasons.most_common():
            print(f"    {reason}: {count}")

    executed = sum(1 for r in runs if r.razorpay_link_id)
    exec_failed = analytics.get("total_executed_events", 0)
    print(f"\n  Executed (links created)  : {executed}")

    print(f"  Pending                   : {analytics.get('pending_count', 0)}")
    print(f"  Recovered                 : {analytics.get('recovered_count', 0)}")
    print(f"  Not Recovered             : {analytics.get('not_recovered_count', 0)}")

    at_risk = analytics.get("total_at_risk_amount", 0)
    recovered_amt = analytics.get("total_recovered_amount", 0)
    rate = analytics.get("recovery_rate", 0.0)

    print(f"\n  Total Amount At Risk      : Rs.{at_risk / 100:,.2f}")
    print(f"  Total Recovered Amount    : Rs.{recovered_amt / 100:,.2f}")
    print(f"  Recovery Rate             : {rate:.2f}%")

    _sep()
    print("\n  Pipeline verification complete.")
    print("  Next steps:")
    print("   1. Open fresh Razorpay Payment Links and complete test-mode payments.")
    print("   2. Re-run Phase 5: POST http://localhost:8000/pipeline/run-phase5")
    print("   3. Check recovered events: GET http://localhost:8000/pipeline/outcomes")
    print("   4. Update DEMO_SCRIPT.md with the best blocked and recovered event IDs.")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    force = "--yes" in sys.argv

    print()
    _sep("=")
    print("  REVIVA -- PIPELINE RESET & VERIFICATION")
    _sep("=")
    print()

    if not _confirm(force):
        print("  Aborted.")
        sys.exit(0)

    init_db()
    db = create_session()

    try:
        step1_clear(db)
        seed_summary = step2_seed(db)
        step3_phase2(db)
        step4_phase3(db)
        step5_phase4(db)
        step6_phase5(db)
        final_report(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()

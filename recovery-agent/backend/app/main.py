"""
main.py — FastAPI application entry point.

Phase 1 endpoints (unchanged):
    GET  /health              → liveness check
    GET  /events              → list all LossEvent records
    GET  /events/summary      → live aggregate stats
    GET  /health/razorpay     → Razorpay test-mode credential check

Phase 2 endpoints:
    POST /pipeline/run-phase2 → run detection + root-cause pipeline
    GET  /pipeline/results    → PipelineRun results joined with LossEvent
    GET  /audit-log/{event_id}→ full audit trail for one event

Phase 3 endpoints:
    POST /pipeline/run-phase3     → run strategy + guardrail pipeline
    GET  /pipeline/blocked        → all runs where guardrail_passed == False
    GET  /pipeline/cleared        → all runs where guardrail_passed == True
    POST /seed/guardrail-test-cases → additive idempotent test case seeder
"""
from __future__ import annotations

import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Load environment variables as early as possible
# ---------------------------------------------------------------------------
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_BACKEND_DIR / ".env", override=False)

from app.database import get_db, init_db  # noqa: E402
from app.models import AuditLog, LossEvent, PipelineRun  # noqa: E402


# ---------------------------------------------------------------------------
# Lifespan — creates database tables on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan context manager (replaces deprecated on_event)."""
    init_db()
    yield
    # Nothing to clean up for Phase 1


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Reviva — Failed Payment Recovery Agent",
    description=(
        "Backend service with SQLite database, ORM models, synthetic data seeding, "
        "Razorpay integration, AI-powered root-cause classification, "
        "deterministic strategy selection, and guardrail enforcement."
    ),
    version="3.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------
def _serialise_event(event: LossEvent) -> dict[str, Any]:
    """
    Convert a LossEvent ORM instance to a JSON-serialisable dict.

    Datetime values are converted to ISO-8601 strings so they survive
    JSON serialisation without a custom encoder.
    """

    def _fmt_dt(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat()

    return {
        "id": event.id,
        "order_id": event.order_id,
        "subscription_id": event.subscription_id,
        "customer_id": event.customer_id,
        "customer_name": event.customer_name,
        "amount": event.amount,
        "failure_code": event.failure_code,
        "status": event.status,
        "created_at": _fmt_dt(event.created_at),
    }


# ---------------------------------------------------------------------------
# ENDPOINT 1 — /health
# ---------------------------------------------------------------------------
@app.get("/health", summary="Application liveness check")
def health_check() -> dict[str, str]:
    """Returns a simple ok status to confirm the application is running."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# ENDPOINT 2 — /events
# ---------------------------------------------------------------------------
@app.get("/events", summary="List all LossEvent records")
def list_events(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns all LossEvent records sorted by id ascending.

    Returns an empty list if the database has not been seeded yet.
    Datetime values are serialised as ISO-8601 strings.
    """
    events: list[LossEvent] = (
        db.query(LossEvent).order_by(LossEvent.id.asc()).all()
    )
    return JSONResponse(content=[_serialise_event(e) for e in events])


# ---------------------------------------------------------------------------
# ENDPOINT 3 — /events/summary
# ---------------------------------------------------------------------------
@app.get("/events/summary", summary="Live aggregate summary of LossEvent records")
def events_summary(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Computes and returns live aggregate statistics from the database.

    Never uses hardcoded expected values — always queries the live data.
    Returns zero values when the database is empty.
    """
    events: list[LossEvent] = db.query(LossEvent).all()

    total = len(events)
    by_failure_code: dict[str, int] = dict(
        Counter(e.failure_code for e in events)
    )
    subscription_count = sum(1 for e in events if e.subscription_id is not None)
    one_off_count = total - subscription_count

    return JSONResponse(
        content={
            "total": total,
            "by_failure_code": by_failure_code,
            "by_payment_type": {
                "subscription": subscription_count,
                "one_off": one_off_count,
            },
        }
    )


# ---------------------------------------------------------------------------
# ENDPOINT 4 — /health/razorpay
# ---------------------------------------------------------------------------
@app.get("/health/razorpay", summary="Razorpay test-mode credential health check")
def health_razorpay() -> JSONResponse:
    """
    Verifies that RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are configured
    and that a lightweight read-only API call to Razorpay succeeds.

    Responses:
        not_configured  — env vars missing or empty
        ok              — credentials valid, API reachable
        error           — credentials present but API call failed
    """
    key_id: str = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret: str = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

    # Guard: credentials not configured
    if not key_id or not key_secret:
        return JSONResponse(
            status_code=200,
            content={
                "status": "not_configured",
                "message": "Razorpay test-mode credentials are not configured",
            },
        )

    # Attempt a lightweight read-only API call using requests directly.
    # We avoid instantiating the Razorpay SDK here because it internally
    # imports pkg_resources (setuptools) which can be unavailable in
    # certain Python 3.12 venvs. Using requests + HTTP Basic Auth is
    # functionally identical and has no extra dependencies.
    try:
        import requests as _requests

        response = _requests.get(
            "https://api.razorpay.com/v1/payments",
            params={"count": 1},
            auth=(key_id, key_secret),
            timeout=10,
        )

        if response.status_code == 200:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "message": "Razorpay test-mode API connection successful",
                },
            )
        elif response.status_code == 401:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "error",
                    "message": "Razorpay authentication failed — check your Key ID and Secret",
                },
            )
        else:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "error",
                    "message": f"Razorpay API returned HTTP {response.status_code}",
                },
            )

    except Exception as exc:
        # Surface a safe, readable error without leaking credentials
        safe_message = str(exc)
        if key_id in safe_message:
            safe_message = safe_message.replace(key_id, "***KEY_ID***")
        if key_secret in safe_message:
            safe_message = safe_message.replace(key_secret, "***KEY_SECRET***")

        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "message": safe_message,
            },
        )


# ===========================================================================
# PHASE 2 ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# ENDPOINT 5 — POST /pipeline/run-phase2
# ---------------------------------------------------------------------------
@app.post("/pipeline/run-phase2", summary="Run Phase 2 detection + root-cause pipeline")
def run_phase2(
    force: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Runs the Phase 2 pipeline over all LossEvent records.

    - Detects confirmed loss events.
    - Classifies root cause via rule-based mapping or Groq LLM fallback.
    - Idempotent by default (force=False skips already-classified events).
    - Use ?force=true to reprocess and update existing classifications.
    """
    from app.pipeline.runner import run_pipeline_phase2

    summary = run_pipeline_phase2(db, force=force)
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# ENDPOINT 6 — GET /pipeline/results
# ---------------------------------------------------------------------------
@app.get("/pipeline/results", summary="List PipelineRun results joined with LossEvent")
def pipeline_results(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns all PipelineRun rows joined with their parent LossEvent.

    Includes root cause classification details for Phase 2 verification.
    """
    runs: list[PipelineRun] = (
        db.query(PipelineRun).order_by(PipelineRun.event_id.asc()).all()
    )

    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    results = []
    for run in runs:
        event: LossEvent | None = run.event
        results.append(
            {
                "event_id":          run.event_id,
                "pipeline_run_id":   run.id,
                "order_id":          event.order_id if event else None,
                "customer_id":       event.customer_id if event else None,
                "failure_code":      event.failure_code if event else None,
                "amount":            event.amount if event else None,
                "subscription_id":   event.subscription_id if event else None,
                "root_cause":        run.root_cause,
                "root_cause_method": run.root_cause_method,
                "timestamp":         _fmt_dt(run.timestamp),
            }
        )

    return JSONResponse(content=results)


# ---------------------------------------------------------------------------
# ENDPOINT 7 — GET /audit-log/{event_id}
# ---------------------------------------------------------------------------
@app.get("/audit-log/{event_id}", summary="Full audit trail for a single LossEvent")
def get_audit_log(
    event_id: int,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Returns all AuditLog entries for the given event_id, ordered by timestamp.

    Returns HTTP 404 if the event does not exist.
    """
    from fastapi import HTTPException

    # Verify event exists
    event = db.query(LossEvent).filter(LossEvent.id == event_id).first()
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=f"LossEvent with id={event_id} not found.",
        )

    logs: list[AuditLog] = (
        db.query(AuditLog)
        .filter(AuditLog.event_id == event_id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )

    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return JSONResponse(
        content=[
            {
                "id":       log.id,
                "event_id": log.event_id,
                "stage":    log.stage,
                "detail":   log.detail,
                "timestamp":_fmt_dt(log.timestamp),
            }
            for log in logs
        ]
    )


# ===========================================================================
# PHASE 3 ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# ENDPOINT 8 — POST /pipeline/run-phase3
# ---------------------------------------------------------------------------
@app.post("/pipeline/run-phase3", summary="Run Phase 3 strategy selection + guardrail pipeline")
def run_phase3(
    force: bool = False,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Runs the Phase 3 pipeline over all PipelineRun records that have a root_cause.

    - Selects a deterministic recovery strategy based on root_cause.
    - Evaluates all four guardrail rules.
    - Updates PipelineRun with strategy, guardrail_passed, guardrail_reason.
    - Idempotent by default (force=False skips already-processed records).
    - Use ?force=true to reprocess and update existing results.
    """
    from app.pipeline.runner import run_pipeline_phase3

    summary = run_pipeline_phase3(db, force=force)
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# ENDPOINT 9 — GET /pipeline/blocked
# ---------------------------------------------------------------------------
@app.get("/pipeline/blocked", summary="List all guardrail-blocked PipelineRun records")
def pipeline_blocked(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns all PipelineRun records where guardrail_passed == False,
    ordered by event_id ascending.

    These are events that were detected, root-cause classified, and strategy
    selected, but blocked from automatic recovery execution.
    """
    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    runs: list[PipelineRun] = (
        db.query(PipelineRun)
        .filter(PipelineRun.guardrail_passed.is_(False))
        .order_by(PipelineRun.event_id.asc())
        .all()
    )

    results = []
    for run in runs:
        event: LossEvent | None = run.event
        results.append(
            {
                "event_id":         run.event_id,
                "pipeline_run_id":  run.id,
                "order_id":         event.order_id if event else None,
                "customer_id":      event.customer_id if event else None,
                "customer_name":    event.customer_name if event else None,
                "amount":           event.amount if event else None,
                "failure_code":     event.failure_code if event else None,
                "root_cause":       run.root_cause,
                "strategy":         run.strategy,
                "guardrail_passed": run.guardrail_passed,
                "guardrail_reason": run.guardrail_reason,
                "timestamp":        _fmt_dt(run.timestamp),
            }
        )

    return JSONResponse(content=results)


# ---------------------------------------------------------------------------
# ENDPOINT 10 — GET /pipeline/cleared
# ---------------------------------------------------------------------------
@app.get("/pipeline/cleared", summary="List all guardrail-cleared PipelineRun records")
def pipeline_cleared(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns all PipelineRun records where guardrail_passed == True,
    ordered by event_id ascending.

    These are the only records eligible for Phase 4 (payment recovery execution).
    """
    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    runs: list[PipelineRun] = (
        db.query(PipelineRun)
        .filter(PipelineRun.guardrail_passed.is_(True))
        .order_by(PipelineRun.event_id.asc())
        .all()
    )

    results = []
    for run in runs:
        event: LossEvent | None = run.event
        results.append(
            {
                "event_id":         run.event_id,
                "pipeline_run_id":  run.id,
                "order_id":         event.order_id if event else None,
                "customer_id":      event.customer_id if event else None,
                "customer_name":    event.customer_name if event else None,
                "amount":           event.amount if event else None,
                "failure_code":     event.failure_code if event else None,
                "root_cause":       run.root_cause,
                "strategy":         run.strategy,
                "guardrail_passed": run.guardrail_passed,
                "timestamp":        _fmt_dt(run.timestamp),
            }
        )

    return JSONResponse(content=results)


# ---------------------------------------------------------------------------
# ENDPOINT 11 — POST /seed/guardrail-test-cases
# ---------------------------------------------------------------------------
@app.post("/seed/guardrail-test-cases", summary="Seed additive guardrail test cases")
def seed_guardrail_test_cases(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Creates dedicated test case LossEvents and PipelineRuns for each guardrail type.

    Additive and idempotent — safe to call multiple times.
    Only creates records that do not already exist (checked by order_id).
    TC2 (cooldown) always refreshes the prior-cleared timestamp to 30 min ago.

    Returns a summary of what was created vs. skipped.
    """
    from app.pipeline.seed_guardrail_test_cases import seed_all

    result = seed_all(db)
    return JSONResponse(content=result)

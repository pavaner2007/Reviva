"""
main.py — FastAPI application entry point.

Endpoints:
    GET  /health              → liveness check
    GET  /events              → list all LossEvent records
    GET  /events/summary      → live aggregate stats
    GET  /health/razorpay     → Razorpay test-mode credential check

    POST /pipeline/run-phase2     → run detection + root-cause pipeline
    GET  /pipeline/results        → PipelineRun results joined with LossEvent
    GET  /audit-log/{event_id}    → full audit trail for one event

    POST /pipeline/run-phase3     → run strategy + guardrail pipeline
    GET  /pipeline/blocked        → all runs where guardrail_passed == False
    GET  /pipeline/cleared        → all runs where guardrail_passed == True
    POST /seed/guardrail-test-cases → additive idempotent test case seeder

    POST /pipeline/run-phase4         → run recovery execution pipeline
    GET  /pipeline/executed           → all runs where razorpay_link_id is set
    POST /pipeline/execute-one/{event_id} → execute one event (demo endpoint)

    POST /pipeline/run-phase5             → measure all executed payment links
    GET  /pipeline/summary                → live recovery analytics summary
    GET  /pipeline/outcomes               → all runs with a non-null outcome
    POST /pipeline/measure-one/{event_id} → measure one event (demo endpoint)
"""
from __future__ import annotations

import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
        "deterministic strategy selection, guardrail enforcement, "
        "automated recovery execution via Razorpay Payment Links, "
        "and live payment outcome measurement."
    ),
    version="5.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow the Vite dev server (Phase 6 frontend)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
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


# ===========================================================================
# PHASE 4 ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# ENDPOINT 12 — POST /pipeline/run-phase4
# ---------------------------------------------------------------------------
@app.post("/pipeline/run-phase4", summary="Run Phase 4 recovery execution pipeline")
def run_phase4(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Runs the Phase 4 execution pipeline over all guardrail-cleared PipelineRun records.

    - Only processes records where guardrail_passed == True.
    - Creates Razorpay test-mode Payment Links for eligible strategies.
    - Idempotent: already-executed events are skipped (no duplicate links created).
    - A 0.5 s rate-limit delay is applied between consecutive Razorpay API calls.
    - Individual failures do not abort the batch.

    Returns:
        Summary with total_eligible, successfully_executed, failed_executions,
        skipped_already_executed, and blocked_rejected counts.
    """
    from app.pipeline.runner import run_pipeline_phase4

    summary = run_pipeline_phase4(db)
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# ENDPOINT 13 — GET /pipeline/executed
# ---------------------------------------------------------------------------
@app.get("/pipeline/executed", summary="List all executed PipelineRun records with Razorpay links")
def pipeline_executed(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns all PipelineRun records where razorpay_link_id is not NULL,
    ordered by event_id ascending.

    These are events that have had a Razorpay Payment Link successfully created.
    """

    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    runs: list[PipelineRun] = (
        db.query(PipelineRun)
        .filter(PipelineRun.razorpay_link_id.isnot(None))
        .order_by(PipelineRun.event_id.asc())
        .all()
    )

    results = []
    for run in runs:
        event: LossEvent | None = run.event
        results.append(
            {
                "event_id":          run.event_id,
                "pipeline_run_id":   run.id,
                "order_id":          event.order_id if event else None,
                "customer_id":       event.customer_id if event else None,
                "customer_name":     event.customer_name if event else None,
                "amount":            event.amount if event else None,
                "root_cause":        run.root_cause,
                "strategy":          run.strategy,
                "action_taken":      run.action_taken,
                "guardrail_passed":  run.guardrail_passed,
                "razorpay_link_id":  run.razorpay_link_id,
                "razorpay_short_url": run.razorpay_short_url,
                "scheduled_for":     _fmt_dt(run.scheduled_for),
                "timestamp":         _fmt_dt(run.timestamp),
            }
        )

    return JSONResponse(content=results)


# ---------------------------------------------------------------------------
# ENDPOINT 14 — POST /pipeline/execute-one/{event_id}
# ---------------------------------------------------------------------------
@app.post(
    "/pipeline/execute-one/{event_id}",
    summary="Execute recovery for a single event (demo endpoint)",
)
def execute_one(event_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    """
    Executes recovery for one specific LossEvent by event_id.

    Intended for live hackathon demos to show real-time Payment Link creation.

    Behaviour:
        - 404  if event not found.
        - 422  if PipelineRun does not exist for this event.
        - 403  if guardrail_passed is not True.
        - 200  with status=rejected if strategy is escalate_to_human_review.
        - 200  with status=skipped  if already executed (idempotency).
        - 200  with status=success  if Payment Link created successfully.
        - 200  with status=failed   if Razorpay API call failed.
    """
    from fastapi import HTTPException
    from app.pipeline.execute import execute_action

    # ── Find the LossEvent ─────────────────────────────────────────────────
    event: LossEvent | None = db.query(LossEvent).filter(LossEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail=f"LossEvent id={event_id} not found.")

    # ── Find its PipelineRun ───────────────────────────────────────────────
    run: PipelineRun | None = (
        db.query(PipelineRun)
        .filter(PipelineRun.event_id == event_id)
        .first()
    )
    if run is None:
        return JSONResponse(
            status_code=422,
            content={
                "event_id": event_id,
                "status": "error",
                "detail": "No PipelineRun found for this event. Run the pipeline first.",
            },
        )

    # ── Guardrail gate ─────────────────────────────────────────────────────
    if run.guardrail_passed is not True:
        return JSONResponse(
            status_code=403,
            content={
                "event_id": event_id,
                "status": "blocked",
                "guardrail_passed": run.guardrail_passed,
                "guardrail_reason": run.guardrail_reason,
                "detail": "Guardrail not passed — execution rejected. Razorpay was not called.",
            },
        )

    # ── Delegate to execute_action() ───────────────────────────────────────
    result = execute_action(event, run, db)

    # Build a rich response that includes extra context for the demo
    response_body = {
        "event_id":          event_id,
        "order_id":          event.order_id,
        "customer_id":       event.customer_id,
        "customer_name":     event.customer_name,
        "amount":            event.amount,
        "root_cause":        run.root_cause,
        "strategy":          run.strategy,
        **result,  # status, razorpay_link_id, razorpay_short_url, etc.
    }

    return JSONResponse(content=response_body)


# ===========================================================================
# PHASE 5 ENDPOINTS
# ===========================================================================

# ---------------------------------------------------------------------------
# ENDPOINT 15 — POST /pipeline/run-phase5
# ---------------------------------------------------------------------------
@app.post("/pipeline/run-phase5", summary="Run Phase 5 payment outcome measurement")
def run_phase5(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Fetches live Razorpay Payment Link status for every executed PipelineRun
    and updates outcome, recovered_amount, and updated_at.

    Unlike earlier phases, this endpoint always re-fetches Razorpay status —
    it does NOT skip records that already have an outcome, so payment
    completions are detected in real time.

    Previously confirmed 'recovered' outcomes are preserved if the Razorpay
    API call fails during measurement.

    Returns:
        Summary with total_checked, recovered_count, pending_count,
        not_recovered_count, and measurement_failed_count.
    """
    from app.pipeline.runner import run_pipeline_phase5

    summary = run_pipeline_phase5(db)
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# ENDPOINT 16 — GET /pipeline/summary
# ---------------------------------------------------------------------------
@app.get("/pipeline/summary", summary="Live recovery analytics summary")
def pipeline_summary(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Computes and returns a live recovery analytics summary from the current
    database state.

    All values are calculated from PipelineRun and LossEvent records directly
    — never from AuditLog history, to prevent double-counting.

    Metrics returned:
        - total_executed_events    : runs with a valid razorpay_link_id
        - total_at_risk_amount     : sum of event.amount for executed runs
        - eligible_at_risk_amount  : sum of event.amount for guardrail-cleared runs
        - total_recovered_amount   : sum of recovered_amount where outcome='recovered'
        - recovery_rate            : (recovered / at_risk) * 100
        - recovered_count          : count of outcome='recovered' runs
        - pending_count            : count of outcome='pending' runs
        - not_recovered_count      : count of outcome='not_recovered' runs
        - guardrail_blocked_value  : sum of event.amount where guardrail_passed=False
        - by_root_cause            : breakdown by each of the 6 root cause categories
    """
    from app.pipeline.measure import get_recovery_summary

    summary = get_recovery_summary(db)
    return JSONResponse(content=summary)


# ---------------------------------------------------------------------------
# ENDPOINT 17 — GET /pipeline/outcomes
# ---------------------------------------------------------------------------
@app.get("/pipeline/outcomes", summary="List all PipelineRun records with a non-null outcome")
def pipeline_outcomes(db: Session = Depends(get_db)) -> JSONResponse:
    """
    Returns all PipelineRun records where outcome is not NULL,
    sorted by updated_at DESC (falls back to timestamp DESC for older rows).

    Includes full context for the hackathon demo:
        event_id, order_id, customer_id, customer_name, amount,
        root_cause, strategy, guardrail_passed, razorpay_link_id,
        razorpay_short_url, outcome, recovered_amount, updated_at.
    """
    from sqlalchemy import case, nullslast

    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    runs: list[PipelineRun] = (
        db.query(PipelineRun)
        .filter(PipelineRun.outcome.isnot(None))
        .order_by(
            nullslast(
                case(
                    (PipelineRun.updated_at.isnot(None), PipelineRun.updated_at),
                    else_=PipelineRun.timestamp,
                ).desc()
            )
        )
        .all()
    )

    results = []
    for run in runs:
        event: LossEvent | None = run.event
        results.append(
            {
                "event_id":          run.event_id,
                "pipeline_run_id":   run.id,
                "order_id":          event.order_id if event else None,
                "customer_id":       event.customer_id if event else None,
                "customer_name":     event.customer_name if event else None,
                "amount":            event.amount if event else None,
                "root_cause":        run.root_cause,
                "strategy":          run.strategy,
                "guardrail_passed":  run.guardrail_passed,
                "razorpay_link_id":  run.razorpay_link_id,
                "razorpay_short_url": run.razorpay_short_url,
                "outcome":           run.outcome,
                "recovered_amount":  run.recovered_amount,
                "updated_at":        _fmt_dt(run.updated_at),
            }
        )

    return JSONResponse(content=results)


# ---------------------------------------------------------------------------
# ENDPOINT 18 — POST /pipeline/measure-one/{event_id}
# ---------------------------------------------------------------------------
@app.post(
    "/pipeline/measure-one/{event_id}",
    summary="Measure payment outcome for a single event (demo endpoint)",
)
def measure_one(event_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    """
    Fetches the live Razorpay Payment Link status for one specific LossEvent
    and updates its outcome in the database.

    Intended for live hackathon demos to show real-time recovery detection.

    Behaviour:
        - 404  if LossEvent not found.
        - 422  if no PipelineRun exists for this event.
        - 422  if PipelineRun has no razorpay_link_id.
        - 200  with full measurement result on success or failure.
    """
    from fastapi import HTTPException
    from app.pipeline.measure import check_payment_status

    # ── Find the LossEvent ──────────────────────────────────────────────────────────────
    event: LossEvent | None = db.query(LossEvent).filter(LossEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail=f"LossEvent id={event_id} not found.")

    # ── Find its PipelineRun ───────────────────────────────────────────────────────
    run: PipelineRun | None = (
        db.query(PipelineRun)
        .filter(PipelineRun.event_id == event_id)
        .first()
    )
    if run is None:
        return JSONResponse(
            status_code=422,
            content={
                "event_id": event_id,
                "error": "No PipelineRun found for this event. Run the pipeline first.",
            },
        )

    # ── Verify razorpay_link_id exists ─────────────────────────────────────────
    if not run.razorpay_link_id or not run.razorpay_link_id.strip():
        return JSONResponse(
            status_code=422,
            content={
                "event_id": event_id,
                "error": (
                    "PipelineRun has no razorpay_link_id. "
                    "Run Phase 4 first to create a Payment Link."
                ),
            },
        )

    # ── Measure ─────────────────────────────────────────────────────────────────
    result = check_payment_status(event, run, db)

    # Build a rich response with event context for the demo
    def _fmt_dt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return JSONResponse(
        content={
            "event_id":          event_id,
            "order_id":          event.order_id,
            "customer_id":       event.customer_id,
            "customer_name":     event.customer_name,
            "razorpay_link_id":  run.razorpay_link_id,
            "razorpay_short_url": run.razorpay_short_url,
            "updated_at":        _fmt_dt(run.updated_at),
            **result,
        }
    )

"""
main.py — FastAPI application entry point for Phase 1.

Endpoints:
    GET  /health              → liveness check
    GET  /events              → list all LossEvent records
    GET  /events/summary      → live aggregate stats
    GET  /health/razorpay     → Razorpay test-mode credential check

Phase 1 only: no AI, no recovery logic, no background workers.
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
from app.models import LossEvent  # noqa: E402


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
    title="Failed Payment Recovery Agent — Phase 1",
    description=(
        "Phase 1 foundation: SQLite database, ORM models, "
        "synthetic data seeding, and API health/verification endpoints."
    ),
    version="1.0.0",
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

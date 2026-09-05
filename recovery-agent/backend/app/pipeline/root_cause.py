"""
pipeline/root_cause.py — Root cause analysis stage (Phase 2, Step 2).

analyze_root_cause(event, db, force=False)

Classifies the failure_code of a LossEvent into exactly one of six
allowed root-cause categories using two strategies:

  1. Rule-based  — deterministic mapping for the five known failure codes.
                   No network call. Always fast.

  2. LLM fallback — Groq SDK with llama-3.3-70b-versatile for unknown codes.
                    Response validated against the allowed list.
                    Gracefully degrades if GROQ_API_KEY is missing or the
                    API call fails.

Idempotency:
    If PipelineRun.root_cause is already set and force=False, the event is
    skipped and the existing result is returned unchanged.

    If force=True, the existing PipelineRun is updated in-place (no new row).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy.orm import Session

from app.models import AuditLog, LossEvent, PipelineRun


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Deterministic mapping: failure_code → root_cause category
RULE_BASED_MAP: dict[str, str] = {
    "card_expired":       "Card Expired",
    "insufficient_funds": "Insufficient Funds",
    "bank_timeout":       "Bank/Network Timeout",
    "otp_failed":         "OTP Verification Failed",
    "issuer_declined":    "Issuer Declined Transaction",
}

# All allowed root-cause categories — LLM must return exactly one of these
ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    [
        "Card Expired",
        "Insufficient Funds",
        "Bank/Network Timeout",
        "OTP Verification Failed",
        "Issuer Declined Transaction",
        "Unclassified — Needs Review",
    ]
)

UNCLASSIFIED = "Unclassified — Needs Review"

# System prompt sent to Groq for every LLM classification request
_SYSTEM_PROMPT = """\
You are a payment failure classifier.

Classify the payment failure into exactly ONE of these categories:

Card Expired
Insufficient Funds
Bank/Network Timeout
OTP Verification Failed
Issuer Declined Transaction
Unclassified — Needs Review

Return ONLY the exact category name.
Do not provide explanations.
Do not add punctuation.
Do not add markdown.
Do not invent categories.
If none of the five specific categories clearly fit, return exactly:
Unclassified — Needs Review\
"""


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------
class RootCauseResult(TypedDict):
    skipped: bool           # True if already classified and force=False
    root_cause: str         # Final root cause label
    root_cause_method: str  # rule-based | llm-fallback | unclassified


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_audit(
    db: Session,
    event_id: int,
    stage: str,
    detail: str,
) -> None:
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


def _call_groq(failure_code: str, amount: int, subscription_id: str | None) -> str:
    """
    Call the Groq API and return the raw response text.

    Raises any exception to the caller so error handling stays in one place.
    Never logs credentials.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"

    from groq import Groq  # lazy import — avoids import error if groq not installed

    client = Groq(api_key=api_key)

    is_subscription = subscription_id is not None
    user_prompt = (
        f"Failure code: {failure_code}\n"
        f"Amount in paise: {amount}\n"
        f"Is subscription: {str(is_subscription).lower()}\n\n"
        "Classify this event into exactly one allowed category."
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0,
        max_completion_tokens=50,
    )

    return response.choices[0].message.content or ""


def _classify_with_llm(
    event: LossEvent,
    db: Session,
) -> tuple[str, str]:
    """
    Attempt LLM classification via Groq.

    Returns (root_cause, root_cause_method).
    Falls back to UNCLASSIFIED on any error.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    # ── No API key configured ───────────────────────────────────────────────
    if not api_key:
        _write_audit(
            db,
            event.id,
            "root_cause",
            (
                f"LLM not configured for fallback classification. "
                f"raw_failure_code={event.failure_code}"
            ),
        )
        return UNCLASSIFIED, "unclassified"

    # ── Attempt the Groq API call ───────────────────────────────────────────
    try:
        raw_response = _call_groq(
            failure_code=event.failure_code,
            amount=event.amount,
            subscription_id=event.subscription_id,
        )
        candidate = raw_response.strip()

    except Exception as exc:
        safe_err = str(exc)
        # Scrub any secrets that might appear in the error string
        api_key_val = os.getenv("GROQ_API_KEY", "")
        if api_key_val and api_key_val in safe_err:
            safe_err = safe_err.replace(api_key_val, "***GROQ_API_KEY***")

        _write_audit(
            db,
            event.id,
            "root_cause",
            (
                f"LLM fallback failed for raw_failure_code={event.failure_code}. "
                f"Error: {safe_err}"
            ),
        )
        return UNCLASSIFIED, "unclassified"

    # ── Validate the response ───────────────────────────────────────────────
    if candidate in ALLOWED_CATEGORIES:
        _write_audit(
            db,
            event.id,
            "root_cause",
            (
                f"Classified as: {candidate} "
                f"(method: llm-fallback, raw_failure_code={event.failure_code})"
            ),
        )
        return candidate, "llm-fallback"

    # Response is invalid — reject it
    _write_audit(
        db,
        event.id,
        "root_cause_validation_failed",
        (
            f"LLM returned an invalid category: '{candidate}'. "
            f"raw_failure_code={event.failure_code}. "
            f"Response rejected. Forced to: '{UNCLASSIFIED}'."
        ),
    )
    return UNCLASSIFIED, "unclassified"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_root_cause(
    event: LossEvent,
    db: Session,
    force: bool = False,
) -> RootCauseResult:
    """
    Classify the root cause of a LossEvent and persist it on PipelineRun.

    Args:
        event: The LossEvent ORM instance.
        db:    An active SQLAlchemy session.
        force: If True, reclassify even if root_cause is already set.
               Updates the existing PipelineRun row — never creates a duplicate.

    Returns:
        RootCauseResult with skipped, root_cause, and root_cause_method.
    """
    # Fetch the associated PipelineRun (must already exist — detect runs first)
    pipeline_run: PipelineRun | None = (
        db.query(PipelineRun)
        .filter(PipelineRun.event_id == event.id)
        .first()
    )
    if pipeline_run is None:
        raise RuntimeError(
            f"No PipelineRun found for event_id={event.id}. "
            "detect_loss() must be called before analyze_root_cause()."
        )

    # ── Skip if already classified and not forced ───────────────────────────
    if pipeline_run.root_cause and not force:
        return RootCauseResult(
            skipped=True,
            root_cause=pipeline_run.root_cause,
            root_cause_method=pipeline_run.root_cause_method or "unclassified",
        )

    # ── Write a forced-reprocessing audit marker ────────────────────────────
    if force and pipeline_run.root_cause:
        _write_audit(
            db,
            event.id,
            "root_cause",
            (
                f"Force reprocessing root cause for event_id={event.id}, "
                f"raw_failure_code={event.failure_code}. "
                f"Previous: '{pipeline_run.root_cause}' ({pipeline_run.root_cause_method})."
            ),
        )

    # ── Rule-based classification ───────────────────────────────────────────
    if event.failure_code in RULE_BASED_MAP:
        root_cause = RULE_BASED_MAP[event.failure_code]
        method = "rule-based"

        _write_audit(
            db,
            event.id,
            "root_cause",
            f"Classified as: {root_cause} (method: rule-based)",
        )

    else:
        # ── LLM fallback ────────────────────────────────────────────────────
        root_cause, method = _classify_with_llm(event, db)

    # ── Persist on PipelineRun ──────────────────────────────────────────────
    pipeline_run.root_cause = root_cause
    pipeline_run.root_cause_method = method
    db.commit()

    return RootCauseResult(
        skipped=False,
        root_cause=root_cause,
        root_cause_method=method,
    )

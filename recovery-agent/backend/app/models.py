"""
models.py — SQLAlchemy ORM models for Phase 1.

Three tables:
  1. LossEvent   — the core failed-payment record
  2. PipelineRun — one row per recovery pipeline attempt (Phase 2+ fills most fields)
  3. AuditLog    — append-only event log per stage (Phase 2+ writes entries)

Phase 1 note:
  PipelineRun and AuditLog are defined here for schema completeness.
  Phase 1 does NOT populate their Phase-2+ columns.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. LossEvent
# ---------------------------------------------------------------------------
class LossEvent(Base):
    """
    Represents a single failed-payment detection event.

    All monetary amounts are stored as INTEGER PAISE to avoid floating-point
    precision issues.  ₹99 → 9900 paise, ₹4999 → 499900 paise.
    """

    __tablename__ = "loss_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    order_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment='Format: "order_" + random alphanumeric string',
    )

    subscription_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment='NULL for one-off payments; ~60% of records have a value',
    )

    customer_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment='Format: CUST_NNNN',
    )

    customer_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment='Realistic Indian customer name',
    )

    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment='Transaction amount in paise (integer only). Range: 9900–499900.',
    )

    failure_code: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment='Raw failure code from the payment gateway',
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="failed",
        comment='Payment status; always "failed" in Phase 1',
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        comment='UTC timestamp of failure event',
    )

    # Relationships (back-populated from child tables)
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        "PipelineRun", back_populates="event", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="event", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<LossEvent id={self.id} order_id={self.order_id!r} "
            f"amount={self.amount} failure_code={self.failure_code!r}>"
        )


# Composite index — useful for future Phase 2 queries by failure_code + status
Index("ix_loss_events_failure_code_status", LossEvent.failure_code, LossEvent.status)


# ---------------------------------------------------------------------------
# 2. PipelineRun
# ---------------------------------------------------------------------------
class PipelineRun(Base):
    """
    Tracks one full execution of the recovery pipeline for a given LossEvent.

    Phase 1: only `event_id` and `timestamp` are meaningful.
    All Phase-2+ columns (root_cause, strategy, …) remain NULL.
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("loss_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Phase 2+ columns — defined here for schema completeness; NULL in Phase 1
    # ------------------------------------------------------------------
    root_cause: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment='Phase 2: classified root cause of the failure',
    )

    strategy: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment='Phase 2: selected recovery strategy',
    )

    guardrail_passed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment='Phase 2: whether the guardrail check passed',
    )

    action_taken: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment='Phase 2: description of the recovery action executed',
    )

    razorpay_link_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment='Phase 2: Razorpay payment-link ID created for recovery',
    )

    outcome: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment='Phase 2: result of the recovery attempt (e.g. "recovered")',
    )

    recovered_amount: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment='Phase 2: amount actually recovered, in paise',
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationship
    event: Mapped["LossEvent"] = relationship("LossEvent", back_populates="pipeline_runs")

    def __repr__(self) -> str:
        return (
            f"<PipelineRun id={self.id} event_id={self.event_id} "
            f"strategy={self.strategy!r} outcome={self.outcome!r}>"
        )


# ---------------------------------------------------------------------------
# 3. AuditLog
# ---------------------------------------------------------------------------
class AuditLog(Base):
    """
    Append-only audit trail for each stage of the recovery pipeline.

    Phase 1: no audit entries are written; table is created for schema completeness.

    Valid stage values (Phase 2+):
        "detect" | "root_cause" | "strategy" | "guardrail" | "execute" | "measure"
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("loss_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    stage: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment='Pipeline stage that generated this log entry',
    )

    detail: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment='Human-readable or JSON detail of the stage result',
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationship
    event: Mapped["LossEvent"] = relationship("LossEvent", back_populates="audit_logs")

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} event_id={self.event_id} "
            f"stage={self.stage!r}>"
        )

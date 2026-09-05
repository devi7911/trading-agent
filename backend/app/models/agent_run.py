import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    EVENT = "event"
    BACKTEST = "backtest"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentRun(Base, UUIDMixin, TimestampMixin):
    """One tick of the agent loop."""

    __tablename__ = "agent_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Nullable: a run is still recorded when the user has no account or no
    # active policy, because "the agent declined to run and here is why" is
    # exactly the kind of thing the audit trail must not lose.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))

    trigger: Mapped[RunTrigger] = mapped_column(String(16), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        String(12), default=RunStatus.RUNNING, nullable=False, index=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    symbols_examined: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    intents_formed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    orders_placed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    denials: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class AgentDecision(Base, UUIDMixin, TimestampMixin):
    """One symbol considered during one run.

    Stores the full input snapshot, the intent, the gate's verdict and the
    resulting order. This is the replay substrate: any historical decision can
    be re-run against new code and compared.
    """

    __tablename__ = "agent_decisions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conviction: Mapped[float] = mapped_column(default=0.0, nullable=False)

    approved: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    denial: Mapped[str | None] = mapped_column(String(40), index=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    order_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL")
    )

    # Everything needed to reproduce this decision.
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    risk_trace: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


__all__ = ["AgentDecision", "AgentRun", "RunStatus", "RunTrigger"]

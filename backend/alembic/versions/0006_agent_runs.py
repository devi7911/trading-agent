"""agent runs and decisions - the replay substrate

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("policy_id", UUID),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="running"),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("symbols_examined", sa.Integer, nullable=False, server_default="0"),
        sa.Column("intents_formed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("orders_placed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("denials", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("summary", postgresql.JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
    )
    for col in ("user_id", "account_id", "status", "correlation_id"):
        op.create_index(f"ix_agent_runs_{col}", "agent_runs", [col])

    op.create_table(
        "agent_decisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("run_id", UUID, sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("requested_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("approved_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("conviction", sa.Float, nullable=False, server_default="0"),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("denial", sa.String(40)),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id", ondelete="SET NULL")),
        sa.Column("signals", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("risk_trace", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("context_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
    )
    for col in ("run_id", "account_id", "instrument_id", "symbol", "approved", "denial"):
        op.create_index(f"ix_agent_decisions_{col}", "agent_decisions", [col])


def downgrade() -> None:
    op.drop_table("agent_decisions")
    op.drop_table("agent_runs")

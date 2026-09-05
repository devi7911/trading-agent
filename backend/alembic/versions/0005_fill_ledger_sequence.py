"""fills: a database-assigned total order for ledger replay

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-05

Wall-clock `filled_at` cannot order the ledger: simulated acknowledgement
latency jitters, so fills from two orders placed together can be timestamped out
of sequence. Replaying them in that order drove a position negative.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fills",
        sa.Column("ledger_seq", sa.BigInteger, sa.Identity(always=True), nullable=False),
    )
    op.create_unique_constraint("uq_fills_ledger_seq", "fills", ["ledger_seq"])
    op.create_index("ix_fills_account_ledger_seq", "fills", ["account_id", "ledger_seq"])


def downgrade() -> None:
    op.drop_index("ix_fills_account_ledger_seq", table_name="fills")
    op.drop_constraint("uq_fills_ledger_seq", "fills", type_="unique")
    op.drop_column("fills", "ledger_seq")

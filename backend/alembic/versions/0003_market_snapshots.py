"""market snapshots: daily index level and breadth

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("index_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("index_return", sa.Numeric(12, 6), nullable=False),
        sa.Column("advancers", sa.Integer, nullable=False, server_default="0"),
        sa.Column("decliners", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unchanged", sa.Integer, nullable=False, server_default="0"),
        sa.Column("new_highs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("new_lows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pct_above_50dma", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("total_volume", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("regime", sa.String(8)),
    )


def downgrade() -> None:
    op.drop_table("market_snapshots")

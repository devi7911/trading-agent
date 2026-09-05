"""execution: orders, fills, positions

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
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
        "orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(12), nullable=False),
        sa.Column("time_in_force", sa.String(8), nullable=False, server_default="day"),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 4)),
        sa.Column("stop_price", sa.Numeric(18, 4)),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("filled_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Numeric(18, 4)),
        sa.Column("commission", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("submitted_at", TS),
        sa.Column("closed_at", TS),
        sa.Column("reject_reason", sa.String(40)),
        sa.Column("note", sa.String(255)),
        sa.Column("parent_order_id", UUID, sa.ForeignKey("orders.id", ondelete="CASCADE")),
        sa.Column("bracket_role", sa.String(16)),
        *_timestamps(),
        sa.UniqueConstraint("account_id", "client_order_id", name="uq_orders_client_order_id"),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.CheckConstraint("filled_quantity >= 0 AND filled_quantity <= quantity",
                           name="ck_orders_filled_within_quantity"),
    )
    op.create_index("ix_orders_account_id", "orders", ["account_id"])
    op.create_index("ix_orders_instrument_id", "orders", ["instrument_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_parent_order_id", "orders", ["parent_order_id"])
    op.create_index("ix_orders_account_status", "orders", ["account_id", "status"])
    op.create_index("ix_orders_instrument_ts", "orders", ["instrument_id", "created_at"])

    op.create_table(
        "fills",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("order_id", UUID, sa.ForeignKey("orders.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("commission", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("filled_at", TS, nullable=False),
        sa.Column("slippage_bps", sa.Numeric(10, 2), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("order_id", "sequence", name="uq_fills_order_sequence"),
        sa.CheckConstraint("quantity > 0", name="ck_fills_quantity_positive"),
        sa.CheckConstraint("price > 0", name="ck_fills_price_positive"),
    )
    op.create_index("ix_fills_order_id", "fills", ["order_id"])
    op.create_index("ix_fills_account_id", "fills", ["account_id"])
    op.create_index("ix_fills_instrument_id", "fills", ["instrument_id"])

    op.create_table(
        "positions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_cost", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("realised_pnl", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("total_commission", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("opened_at", TS),
        sa.Column("closed_at", TS),
        *_timestamps(),
        sa.UniqueConstraint("account_id", "instrument_id", name="uq_positions_instrument"),
    )
    op.create_index("ix_positions_account_id", "positions", ["account_id"])
    op.create_index("ix_positions_instrument_id", "positions", ["instrument_id"])


def downgrade() -> None:
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")

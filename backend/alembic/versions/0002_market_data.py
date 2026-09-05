"""market data: bars hypertable, news, corporate events, instrument fundamentals

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # --- instruments: fundamentals and generator inputs ---
    op.add_column("instruments", sa.Column("listed_on", sa.Date()))
    op.add_column("instruments", sa.Column("shares_outstanding", sa.BigInteger()))
    op.add_column("instruments", sa.Column("beta", sa.Float()))
    op.add_column("instruments", sa.Column("annual_vol", sa.Float()))
    op.add_column(
        "instruments",
        sa.Column("sim_params", postgresql.JSONB, nullable=False, server_default="{}"),
    )

    # --- bars ---
    op.create_table(
        "bars",
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("ts", TS, nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False, server_default="1d"),
        sa.Column("open", sa.Numeric(18, 4), nullable=False),
        sa.Column("high", sa.Numeric(18, 4), nullable=False),
        sa.Column("low", sa.Numeric(18, 4), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("volume", sa.BigInteger, nullable=False),
        sa.PrimaryKeyConstraint("instrument_id", "ts", "timeframe", name="pk_bars"),
    )
    op.create_index("ix_bars_instrument_timeframe_ts", "bars",
                    ["instrument_id", "timeframe", "ts"])

    # Timescale hypertable. Falls back to a plain table if the extension is absent,
    # so the schema still applies on a stock Postgres (CI, a colleague's laptop).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'bars', 'ts',
                    chunk_time_interval => INTERVAL '90 days',
                    migrate_data => TRUE
                );
            END IF;
        END $$;
        """
    )

    # --- news ---
    op.create_table(
        "news_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE")),
        sa.Column("published_at", TS, nullable=False),
        sa.Column("headline", sa.String(300), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("source", sa.String(64), nullable=False, server_default="SIM WIRE"),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("sentiment", sa.Float, nullable=False, server_default="0"),
        sa.Column("relation", sa.String(16), nullable=False, server_default="noise"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_news_items_instrument_id", "news_items", ["instrument_id"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])
    op.create_index("ix_news_items_category", "news_items", ["category"])

    # --- corporate events ---
    op.create_table(
        "corporate_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("occurs_at", TS, nullable=False),
        sa.Column("eps_estimate", sa.Numeric(12, 4)),
        sa.Column("eps_actual", sa.Numeric(12, 4)),
        sa.Column("ratio", sa.Numeric(10, 4)),
        sa.Column("amount", sa.Numeric(12, 4)),
        sa.Column("note", sa.String(255)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_corporate_events_instrument_id", "corporate_events", ["instrument_id"])
    op.create_index("ix_corporate_events_event_type", "corporate_events", ["event_type"])
    op.create_index("ix_corporate_events_occurs_at", "corporate_events", ["occurs_at"])


def downgrade() -> None:
    op.drop_table("corporate_events")
    op.drop_table("news_items")
    op.drop_table("bars")
    for col in ("sim_params", "annual_vol", "beta", "shares_outstanding", "listed_on"):
        op.drop_column("instruments", col)

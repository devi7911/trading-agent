"""agent_runs.account_id nullable

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-05

A run must still be recorded when the user has no account or no active policy -
"the agent declined to run, and here is why" belongs in the audit trail. The
previous code substituted the user id, which violated the foreign key.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("agent_runs", "account_id",
                    existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM agent_runs WHERE account_id IS NULL"))
    op.alter_column("agent_runs", "account_id",
                    existing_type=postgresql.UUID(as_uuid=True), nullable=False)

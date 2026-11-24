"""песочницы демо

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24 10:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("sandbox_token", sa.String(length=64), nullable=True))
    op.add_column("organizations", sa.Column("sandbox_claimed_at", sa.DateTime(), nullable=True))
    op.add_column("organizations", sa.Column("sandbox_seen_at", sa.DateTime(), nullable=True))
    op.create_index("ix_organizations_sandbox_token", "organizations", ["sandbox_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_organizations_sandbox_token", table_name="organizations")
    op.drop_column("organizations", "sandbox_seen_at")
    op.drop_column("organizations", "sandbox_claimed_at")
    op.drop_column("organizations", "sandbox_token")

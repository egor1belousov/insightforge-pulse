"""конструктор материалов и тесты

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24 21:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("courses", sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(
        "courses", sa.Column("status", sa.String(length=20), nullable=False, server_default="published")
    )
    op.add_column("tests", sa.Column("pass_score", sa.Float(), nullable=False, server_default="0.7"))
    op.add_column(
        "tests", sa.Column("difficulty", sa.String(length=20), nullable=False, server_default="medium")
    )
    op.add_column(
        "test_questions", sa.Column("qtype", sa.String(length=12), nullable=False, server_default="single")
    )
    op.add_column(
        "test_questions", sa.Column("correct_multi", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("test_questions", sa.Column("source", sa.Text(), nullable=False, server_default=""))
    op.add_column("assignments", sa.Column("sections_done", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("assignments", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    for t, c in (
        ("assignments", "attempts"),
        ("assignments", "sections_done"),
        ("test_questions", "source"),
        ("test_questions", "correct_multi"),
        ("test_questions", "qtype"),
        ("tests", "difficulty"),
        ("tests", "pass_score"),
        ("courses", "status"),
        ("courses", "sections"),
        ("courses", "tags"),
    ):
        op.drop_column(t, c)

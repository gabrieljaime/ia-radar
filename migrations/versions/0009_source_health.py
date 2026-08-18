"""Persist the latest source health check result for the operator dashboard.

Health is written only by scripts/check_sources.py (the existing daily
ai-radar-health timer); the web dashboard reads this table instead of
issuing live HTTP requests to sources on every page load.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_health",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("http_status", sa.String(20), nullable=True),
        sa.Column("items_found", sa.Integer(), nullable=False),
        sa.Column("latest_item_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index("ix_source_health_source_id", "source_health", ["source_id"])


def downgrade() -> None:
    op.drop_table("source_health")

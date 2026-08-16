"""Persist idempotent Telegram digest deliveries."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "digests" in inspector.get_table_names():
        return
    op.create_table(
        "digests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("telegram_message_id", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_digests_period_start", "digests", ["period_start"])
    op.create_index("ix_digests_period_end", "digests", ["period_end"])
    op.create_index("ix_digests_status", "digests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_digests_status", table_name="digests")
    op.drop_index("ix_digests_period_end", table_name="digests")
    op.drop_index("ix_digests_period_start", table_name="digests")
    op.drop_table("digests")

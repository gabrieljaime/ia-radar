"""Persist source-side modification timestamp separately from publication."""

import sqlalchemy as sa
from alembic import op

revision = "0007_source_modified"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "articles", sa.Column("source_last_modified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("articles", "source_last_modified_at")

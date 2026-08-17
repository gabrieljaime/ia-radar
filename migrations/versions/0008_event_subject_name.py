"""Persist the LLM-verified subject name so a validated factual anchor is not discarded."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007_source_modified"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("subject_name", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "subject_name")

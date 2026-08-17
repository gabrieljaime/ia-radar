"""Persist presentation metadata for dynamic profiles."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("profiles")}
    if "icon" not in columns:
        op.add_column(
            "profiles", sa.Column("icon", sa.String(length=20), nullable=False, server_default="•")
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("profiles")}
    if "icon" in columns:
        op.drop_column("profiles", "icon")

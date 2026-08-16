"""Add LLM usage accounting to pipeline runs."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


_COLUMNS = (
    sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
)


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pipeline_runs")}
    for column in _COLUMNS:
        if column.name not in existing:
            op.add_column("pipeline_runs", column)


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pipeline_runs")}
    for column in reversed(_COLUMNS):
        if column.name in existing:
            op.drop_column("pipeline_runs", column.name)

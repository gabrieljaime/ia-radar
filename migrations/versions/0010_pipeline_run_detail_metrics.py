"""Persist per-run funnel metrics already computed by the pipeline but not previously stored.

app.application.radar_service already tracks candidates_new, prefilter_passed,
primary_bypass_passed, pending_reanalysis, evidence_reanalysis, analysis_retries
and llm_call_limit_reached on the in-memory PipelineResult and logs them, but
never persisted them to pipeline_runs. The operator dashboard's Run Detail
screen needs them, so this only adds columns and RadarRepository.finish_run
now writes the values it already has -- no pipeline/scoring behavior changes.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_NEW_INT_COLUMNS = (
    "candidates_new",
    "prefilter_passed",
    "primary_bypass_passed",
    "pending_reanalysis",
    "evidence_reanalysis",
    "analysis_retries",
)


def upgrade() -> None:
    for name in _NEW_INT_COLUMNS:
        op.add_column(
            "pipeline_runs", sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        )
    op.add_column(
        "pipeline_runs",
        sa.Column(
            "llm_call_limit_reached", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    for name in _NEW_INT_COLUMNS:
        op.alter_column("pipeline_runs", name, server_default=None)
    op.alter_column("pipeline_runs", "llm_call_limit_reached", server_default=None)


def downgrade() -> None:
    op.drop_column("pipeline_runs", "llm_call_limit_reached")
    for name in _NEW_INT_COLUMNS:
        op.drop_column("pipeline_runs", name)

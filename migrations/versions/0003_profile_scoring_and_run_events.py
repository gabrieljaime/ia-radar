"""Separate profile relevance from alert scoring and link analyzed events to runs."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    event_columns = {column["name"] for column in inspector.get_columns("events")}
    if "analyzed_run_id" not in event_columns:
        op.add_column("events", sa.Column("analyzed_run_id", sa.Uuid(), nullable=True))

    inspector = sa.inspect(op.get_bind())
    event_foreign_keys = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys("events")
    }
    if ("analyzed_run_id",) not in event_foreign_keys:
        op.create_foreign_key(
            "fk_events_analyzed_run_id",
            "events",
            "pipeline_runs",
            ["analyzed_run_id"],
            ["id"],
        )
    event_indexes = {tuple(index["column_names"]) for index in inspector.get_indexes("events")}
    if ("analyzed_run_id",) not in event_indexes:
        op.create_index("ix_events_analyzed_run_id", "events", ["analyzed_run_id"])

    score_columns = {column["name"] for column in inspector.get_columns("event_scores")}
    score_checks = {
        (constraint.get("sqltext") or "").replace(" ", "").lower()
        for constraint in inspector.get_check_constraints("event_scores")
    }
    for name in (
        "novelty_score",
        "actionability_score",
        "strategic_impact_score",
        "alert_score",
    ):
        if name not in score_columns:
            op.add_column(
                "event_scores", sa.Column(name, sa.Integer(), nullable=False, server_default="0")
            )
        expression = f"{name}between0and100"
        if not any(expression in check for check in score_checks):
            op.create_check_constraint(
                f"ck_event_scores_{name}_range",
                "event_scores",
                f"{name} BETWEEN 0 AND 100",
            )


def downgrade() -> None:
    for name in reversed(
        ("novelty_score", "actionability_score", "strategic_impact_score", "alert_score")
    ):
        op.drop_constraint(f"ck_event_scores_{name}_range", "event_scores", type_="check")
        op.drop_column("event_scores", name)
    op.drop_index("ix_events_analyzed_run_id", table_name="events")
    op.drop_constraint("fk_events_analyzed_run_id", "events", type_="foreignkey")
    op.drop_column("events", "analyzed_run_id")

"""Initial event-centric schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("base_url", sa.String(2000), nullable=False),
        sa.Column("trust_level", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "base_url"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("normalized_title", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("what_happened", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("what_changed", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("discard_reason", sa.String(40), nullable=True),
        sa.Column("novelty_score", sa.Integer(), nullable=False),
        sa.Column("credibility_score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("hype_probability", sa.Float(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1"),
        sa.CheckConstraint("credibility_score BETWEEN 0 AND 100"),
        sa.CheckConstraint("hype_probability BETWEEN 0 AND 1"),
        sa.CheckConstraint("novelty_score BETWEEN 0 AND 100"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_discard_reason", "events", ["discard_reason"])
    op.create_index("ix_events_event_hash", "events", ["event_hash"], unique=True)
    op.create_index("ix_events_normalized_title", "events", ["normalized_title"])
    op.create_index("ix_events_status", "events", ["status"])
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("collected", sa.Integer(), nullable=False),
        sa.Column("analyzed", sa.Integer(), nullable=False),
        sa.Column("alerts_sent", sa.Integer(), nullable=False),
        sa.Column("discard_counts", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(1000), nullable=True),
        sa.Column("canonical_url", sa.String(2000), nullable=False),
        sa.Column("normalized_title", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("summary_raw", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("discard_reason", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
    )
    for name in (
        "content_hash",
        "discard_reason",
        "event_id",
        "normalized_title",
        "published_at",
        "source_id",
        "status",
    ):
        op.create_index(f"ix_articles_{name}", "articles", [name])
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(30), nullable=False),
        sa.Column("provider_message_id", sa.String(100), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "alert_type", "channel"),
    )
    op.create_index("ix_alerts_delivery_status", "alerts", ["delivery_status"])
    op.create_index("ix_alerts_event_id", "alerts", ["event_id"])
    op.create_table(
        "candidate_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("canonical_url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("discard_reason", sa.String(40), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("article_id", "discard_reason", "event_id", "status"):
        op.create_index(f"ix_candidate_records_{name}", "candidate_records", [name])
    op.create_table(
        "event_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("relevance_score", sa.Integer(), nullable=False),
        sa.Column("relevance_reason", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("related_topics", sa.JSON(), nullable=False),
        sa.Column("related_classes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relevance_score BETWEEN 0 AND 100"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "profile_id"),
    )
    op.create_index("ix_event_scores_event_id", "event_scores", ["event_id"])
    op.create_index("ix_event_scores_profile_id", "event_scores", ["profile_id"])


def downgrade() -> None:
    op.drop_table("event_scores")
    op.drop_table("candidate_records")
    op.drop_table("alerts")
    op.drop_table("articles")
    op.drop_table("profiles")
    op.drop_table("pipeline_runs")
    op.drop_table("events")
    op.drop_table("sources")

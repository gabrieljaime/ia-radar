"""Track event evidence upgrades and primary-source verification."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    source_columns = {column["name"] for column in inspector.get_columns("sources")}
    if "requires_primary_verification" not in source_columns:
        op.add_column(
            "sources",
            sa.Column(
                "requires_primary_verification",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    event_columns = {column["name"] for column in inspector.get_columns("events")}
    columns = (
        sa.Column("origin_article_id", sa.Uuid(), nullable=True),
        sa.Column("analysis_article_id", sa.Uuid(), nullable=True),
        sa.Column(
            "primary_source_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("primary_source_url", sa.String(length=2000), nullable=True),
        sa.Column("evidence_upgrade_reason", sa.String(length=100), nullable=True),
        sa.Column("last_evidence_upgrade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_count", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in columns:
        if column.name not in event_columns:
            op.add_column("events", column)

    foreign_keys = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("events")
    }
    if ("origin_article_id",) not in foreign_keys:
        op.create_foreign_key(
            "fk_events_origin_article_id", "events", "articles", ["origin_article_id"], ["id"]
        )
    if ("analysis_article_id",) not in foreign_keys:
        op.create_foreign_key(
            "fk_events_analysis_article_id",
            "events",
            "articles",
            ["analysis_article_id"],
            ["id"],
        )


def downgrade() -> None:
    op.drop_constraint("fk_events_analysis_article_id", "events", type_="foreignkey")
    op.drop_constraint("fk_events_origin_article_id", "events", type_="foreignkey")
    for name in (
        "analysis_count",
        "last_evidence_upgrade_at",
        "evidence_upgrade_reason",
        "primary_source_url",
        "primary_source_verified",
        "analysis_article_id",
        "origin_article_id",
    ):
        op.drop_column("events", name)
    op.drop_column("sources", "requires_primary_verification")

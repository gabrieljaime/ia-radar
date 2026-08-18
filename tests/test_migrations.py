import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import StaticCollector, StaticLLM
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.application.radar_service import RadarService
from app.db.repository import RadarRepository
from app.domain.models import Candidate

pytestmark = pytest.mark.postgres_integration


@pytest.fixture
def empty_postgres_database():
    configured_url = os.getenv("TEST_POSTGRES_DATABASE_URL")
    if not configured_url:
        pytest.skip("TEST_POSTGRES_DATABASE_URL is not configured")

    base_url = make_url(configured_url)
    database_name = f"ai_radar_migration_{uuid4().hex}"
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    database_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    try:
        yield database_url
    finally:
        admin_engine.dispose()
        cleanup_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with cleanup_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        cleanup_engine.dispose()


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def column_names(database_url: str, table_name: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        return [column["name"] for column in inspect(engine).get_columns(table_name)]
    finally:
        engine.dispose()


def table_names(database_url: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        return inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_fresh_postgres_migration_walk_reaches_head_idempotently(empty_postgres_database):
    database_url = empty_postgres_database

    run_alembic(database_url, "upgrade", "0001")
    assert "source_last_modified_at" not in column_names(database_url, "articles")
    assert "subject_name" not in column_names(database_url, "events")
    assert "analyzed_run_id" not in column_names(database_url, "events")
    assert "icon" not in column_names(database_url, "profiles")
    assert "requires_primary_verification" not in column_names(database_url, "sources")
    assert "llm_calls" not in column_names(database_url, "pipeline_runs")
    assert "alert_score" not in column_names(database_url, "event_scores")
    assert "digests" not in table_names(database_url)

    run_alembic(database_url, "upgrade", "0007_source_modified")
    assert column_names(database_url, "articles").count("source_last_modified_at") == 1
    assert "subject_name" not in column_names(database_url, "events")

    run_alembic(database_url, "upgrade", "head")
    assert column_names(database_url, "articles").count("source_last_modified_at") == 1
    assert column_names(database_url, "events").count("subject_name") == 1
    assert {
        "analyzed_run_id",
        "origin_article_id",
        "analysis_article_id",
        "primary_source_verified",
        "primary_source_url",
        "evidence_upgrade_reason",
        "last_evidence_upgrade_at",
        "analysis_count",
    } <= set(column_names(database_url, "events"))
    assert {"llm_calls", "input_tokens", "output_tokens", "estimated_cost_usd"} <= set(
        column_names(database_url, "pipeline_runs")
    )
    assert {
        "novelty_score",
        "actionability_score",
        "strategic_impact_score",
        "alert_score",
    } <= set(column_names(database_url, "event_scores"))
    assert "requires_primary_verification" in column_names(database_url, "sources")
    assert "icon" in column_names(database_url, "profiles")
    assert "digests" in table_names(database_url)
    assert "source_health" in table_names(database_url)
    assert {
        "candidates_new",
        "prefilter_passed",
        "primary_bypass_passed",
        "pending_reanalysis",
        "evidence_reanalysis",
        "analysis_retries",
        "llm_call_limit_reached",
    } <= set(column_names(database_url, "pipeline_runs"))
    current = run_alembic(database_url, "current").stdout
    assert "0010 (head)" in current

    run_alembic(database_url, "upgrade", "head")
    assert column_names(database_url, "articles").count("source_last_modified_at") == 1
    assert column_names(database_url, "events").count("subject_name") == 1

    run_alembic(database_url, "downgrade", "base")
    assert not {
        "sources",
        "events",
        "pipeline_runs",
        "profiles",
        "articles",
        "alerts",
        "candidate_records",
        "event_scores",
        "digests",
        "source_health",
    } & set(table_names(database_url))


async def test_fresh_postgres_backfill_analyzes_only_recent_items(
    empty_postgres_database, profiles, analysis
):
    database_url = empty_postgres_database
    run_alembic(database_url, "upgrade", "head")
    now = datetime.now(UTC)

    def item(index: int, published_at: datetime) -> Candidate:
        identity = hashlib.sha256(str(index).encode()).hexdigest()
        title = f"{identity} AI agent release"
        return Candidate(
            source_name="Bootstrap fixture",
            source_url="https://fixture.example/feed",
            source_trust=100,
            source_is_primary=True,
            title=title,
            url=f"https://fixture.example/{index}",
            summary=f"{title} with tool calling capability {index}",
            published_at=published_at,
        )

    candidates = [item(index, now - timedelta(days=365)) for index in range(100)]
    candidates.extend(item(100 + index, now) for index in range(5))
    llm = StaticLLM(analysis)
    engine = create_engine(database_url)
    try:
        with Session(engine, expire_on_commit=False) as session:
            result = await RadarService(
                StaticCollector(candidates),
                llm,
                RadarRepository(session),
                profiles,
                None,
                lookback_hours=48,
                prefilter_min_score=0,
            ).run()
    finally:
        engine.dispose()

    assert result.discarded["too_old"] == 100
    assert result.analyzed == result.llm_calls == llm.calls == 5

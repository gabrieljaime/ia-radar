import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Alert, Article, Digest, Event, PipelineRun, Source
from app.db.repository import RadarRepository

pytestmark = pytest.mark.postgres_integration


@pytest.fixture
def postgres_engine():
    url = os.getenv("TEST_POSTGRES_DATABASE_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_DATABASE_URL is not configured")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_schema_uses_native_types_and_constraints(postgres_engine):
    inspector = inspect(postgres_engine)
    run_columns = {column["name"]: column for column in inspector.get_columns("pipeline_runs")}
    assert str(run_columns["id"]["type"]) == "UUID"
    assert run_columns["started_at"]["type"].timezone is True
    assert str(run_columns["discard_counts"]["type"]) in {"JSON", "JSONB"}

    alert_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("alerts")
    }
    digest_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("digests")
    }
    assert ("event_id", "alert_type", "channel") in alert_unique
    assert ("idempotency_key",) in digest_unique


def test_postgres_uuid_timezone_json_and_delivery_idempotency(postgres_engine):
    with Session(postgres_engine, expire_on_commit=False) as session:
        run = PipelineRun(discard_counts={"duplicate": 2}, error_summary=["fixture"])
        event = Event(event_hash=uuid4().hex, normalized_title="integration", title="Integration")
        source = Source(
            name="Integration source",
            source_type="rss",
            base_url=f"https://integration.example/{uuid4()}",
            trust_level=100,
            is_primary=True,
        )
        session.add_all([run, event, source])
        session.commit()
        article = Article(
            event_id=event.id,
            source_id=source.id,
            canonical_url=f"https://integration.example/article/{uuid4()}",
            normalized_title="integration",
            title="Integration",
            content_hash=uuid4().hex,
        )
        session.add(article)
        session.commit()
        event.origin_article_id = article.id
        session.commit()
        session.refresh(run)
        assert run.id.version == 4
        assert run.started_at.tzinfo is not None
        assert run.discard_counts == {"duplicate": 2}

        repository = RadarRepository(session)
        first = repository.reserve_alert(event.id, "fingerprint")
        second = repository.reserve_alert(event.id, "another")
        assert first is not None
        assert second is None
        assert session.scalar(select(Alert).where(Alert.event_id == event.id)) is not None

        digest = Digest(
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC),
            content_hash=uuid4().hex,
            idempotency_key=uuid4().hex,
        )
        session.add(digest)
        session.commit()
        assert session.get(Digest, digest.id).period_start.tzinfo is not None

        duplicate = Digest(
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC),
            content_hash=uuid4().hex,
            idempotency_key=digest.idempotency_key,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_postgres_advisory_lock_is_exclusive_and_reusable(postgres_engine):
    with Session(postgres_engine) as first_session, Session(postgres_engine) as second_session:
        first = RadarRepository(first_session)
        second = RadarRepository(second_session)
        assert first.try_acquire_run_lock() is True
        assert second.try_acquire_run_lock() is False
        first.release_run_lock()
        assert second.try_acquire_run_lock() is True
        second.release_run_lock()

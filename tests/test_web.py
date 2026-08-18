from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Article,
    Base,
    Event,
    EventScore,
    PipelineRun,
    Profile,
    Source,
    SourceHealth,
)
from app.main import app
from app.web.deps import get_session


@pytest.fixture
def db_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(db_session_factory):
    def override_get_session():
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(db_session_factory):
    with db_session_factory() as session:
        source = Source(
            name="Anthropic Changelog",
            source_type="web_changelog",
            base_url="https://anthropic.example/changelog",
            trust_level=90,
            is_primary=True,
            requires_primary_verification=False,
            enabled=True,
        )
        session.add(source)
        session.flush()

        session.add(
            SourceHealth(
                source_id=source.id,
                status="OK",
                http_status="200",
                items_found=5,
                latest_item_at=datetime.now(UTC),
                checked_at=datetime.now(UTC),
            )
        )

        profile = Profile(
            slug="agent-developer", name="AI Agent Developer", icon="🤖", enabled=True
        )
        session.add(profile)
        session.flush()

        run = PipelineRun(
            status="completed",
            collected=12,
            analyzed=3,
            alerts_sent=1,
            llm_calls=3,
            input_tokens=1000,
            output_tokens=200,
            estimated_cost_usd=0.0,
            candidates_new=8,
            prefilter_passed=5,
            primary_bypass_passed=1,
            pending_reanalysis=0,
            evidence_reanalysis=0,
            analysis_retries=0,
            llm_call_limit_reached=False,
            discard_counts={"too_old": 2, "low_relevance": 1},
            error_summary=[],
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()

        published_at = datetime(2026, 8, 18, 11, 3, tzinfo=UTC)
        event = Event(
            analyzed_run_id=run.id,
            event_hash="hash-1",
            normalized_title="new model released",
            title="New Model Released",
            subject_name="Example Model 1.0",
            what_happened="A new model was released.",
            why_it_matters="It changes the landscape.",
            status="analyzed",
            novelty_score=80,
            credibility_score=80,
            confidence=0.9,
            hype_probability=0.1,
            primary_source_verified=True,
            first_seen_at=published_at,
            last_seen_at=published_at,
        )
        session.add(event)
        session.flush()

        article = Article(
            event_id=event.id,
            source_id=source.id,
            canonical_url="https://anthropic.example/changelog/new-model",
            normalized_title="new model released",
            title="New Model Released",
            summary_raw="Summary",
            published_at=published_at,
            content_hash="content-hash-1",
            status="new",
        )
        session.add(article)
        session.flush()
        event.primary_source_url = article.canonical_url

        score = EventScore(
            event_id=event.id,
            profile_id=profile.id,
            relevance_score=95,
            novelty_score=80,
            actionability_score=70,
            strategic_impact_score=60,
            alert_score=92,
            relevance_reason="Highly relevant to agent developers.",
            suggested_action="Evaluate the new model.",
            related_topics=["agents", "tooling"],
            related_classes=[1, 2],
        )
        session.add(score)
        session.commit()

        return {"event_id": event.id, "run_id": run.id, "source_id": source.id}


def test_overview_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "No events detected yet." in response.text


def test_overview_with_data(client, seeded):
    response = client.get("/")
    assert response.status_code == 200
    assert "New Model Released" in response.text
    assert "92" in response.text


def test_radar_empty_state(client):
    response = client.get("/radar")
    assert response.status_code == 200
    assert "No events detected yet." in response.text


def test_radar_lists_event(client, seeded):
    response = client.get("/radar")
    assert response.status_code == 200
    assert "New Model Released" in response.text
    assert "AI Agent Developer" in response.text


def test_radar_profile_filter(client, seeded):
    response = client.get("/radar?profile=agent-developer")
    assert response.status_code == 200
    assert "New Model Released" in response.text

    response = client.get("/radar?profile=does-not-exist")
    assert response.status_code == 200
    assert "No events detected yet." in response.text


def test_radar_min_alert_filter(client, seeded):
    response = client.get("/radar?min_alert=95")
    assert response.status_code == 200
    assert "No events detected yet." in response.text


def test_radar_pagination(client, db_session_factory):
    with db_session_factory() as session:
        source = Source(
            name="RSS Source",
            source_type="rss",
            base_url="https://example.test/feed",
            trust_level=50,
            is_primary=True,
            enabled=True,
        )
        session.add(source)
        session.flush()
        for index in range(30):
            event = Event(
                event_hash=f"hash-{index}",
                normalized_title=f"event {index}",
                title=f"Event {index}",
                status="analyzed",
                confidence=0.5,
                hype_probability=0.1,
                first_seen_at=datetime.now(UTC) - timedelta(minutes=index),
                last_seen_at=datetime.now(UTC) - timedelta(minutes=index),
            )
            session.add(event)
        session.commit()

    first_page = client.get("/radar")
    assert first_page.status_code == 200
    assert "Page 1 of 2" in first_page.text

    second_page = client.get("/radar?page=2")
    assert second_page.status_code == 200
    assert "Page 2 of 2" in second_page.text


def test_event_detail(client, seeded):
    response = client.get(f"/radar/{seeded['event_id']}")
    assert response.status_code == 200
    assert "New Model Released" in response.text
    assert "Evaluate the new model." in response.text
    assert "agents" in response.text


def test_event_detail_not_found(client):
    response = client.get(f"/radar/{uuid4()}")
    assert response.status_code == 404
    assert "404" in response.text


def test_sources_page(client, seeded):
    response = client.get("/sources")
    assert response.status_code == 200
    assert "Anthropic Changelog" in response.text
    assert "healthy" in response.text


def test_sources_page_empty_state(client):
    response = client.get("/sources")
    assert response.status_code == 200
    assert "No sources configured yet." in response.text


def test_runs_page(client, seeded):
    response = client.get("/runs")
    assert response.status_code == 200
    assert "completed" in response.text


def test_run_detail(client, seeded):
    response = client.get(f"/runs/{seeded['run_id']}")
    assert response.status_code == 200
    assert "New Model Released" in response.text
    assert "Cost estimation not configured" in response.text
    assert "too_old" in response.text


def test_run_detail_not_found(client):
    response = client.get(f"/runs/{uuid4()}")
    assert response.status_code == 404


def test_timezone_conversion(client, seeded):
    response = client.get(f"/radar/{seeded['event_id']}")
    assert response.status_code == 200
    assert "08:03" in response.text


def test_404_page(client):
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    assert "404" in response.text


def test_templates_never_leak_secrets(client, seeded, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.setenv("LLM_API_KEY", "super-secret-key")
    paths = (
        "/",
        "/radar",
        f"/radar/{seeded['event_id']}",
        "/sources",
        "/runs",
        f"/runs/{seeded['run_id']}",
    )
    for path in paths:
        response = client.get(path)
        assert "super-secret-token" not in response.text
        assert "super-secret-key" not in response.text
        assert "postgresql://" not in response.text.lower()
        assert "psycopg" not in response.text.lower()


def test_health_and_ready_untouched(client):
    assert client.get("/health").status_code == 200

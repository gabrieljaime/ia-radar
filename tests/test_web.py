from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

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
from app.web.timeutil import relative_time


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

        published_at = datetime.now(UTC) - timedelta(days=1)
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

        return {
            "event_id": event.id,
            "run_id": run.id,
            "source_id": source.id,
            "published_at": published_at,
        }


def _make_source_and_profile(session):
    source = Source(
        name="Test Source",
        source_type="rss",
        base_url="https://example.test/feed",
        trust_level=50,
        is_primary=True,
        enabled=True,
    )
    session.add(source)
    profile = Profile(slug="agent-developer", name="AI Agent Developer", icon="🤖", enabled=True)
    session.add(profile)
    session.flush()
    return source, profile


def _seed_event(
    session,
    *,
    source,
    profile,
    title,
    published_at=None,
    first_seen_at=None,
    alert_score=80,
    with_article=True,
):
    first_seen_at = first_seen_at or datetime.now(UTC)
    event = Event(
        event_hash=f"hash-{title}",
        normalized_title=title.lower(),
        title=title,
        status="analyzed",
        confidence=0.8,
        hype_probability=0.1,
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )
    session.add(event)
    session.flush()
    if with_article:
        article = Article(
            event_id=event.id,
            source_id=source.id,
            canonical_url=f"https://example.test/{title.lower().replace(' ', '-')}",
            normalized_title=title.lower(),
            title=title,
            summary_raw="Summary",
            published_at=published_at,
            content_hash=f"content-{title}",
            status="new",
        )
        session.add(article)
    score = EventScore(
        event_id=event.id,
        profile_id=profile.id,
        relevance_score=90,
        novelty_score=80,
        actionability_score=70,
        strategic_impact_score=60,
        alert_score=alert_score,
        relevance_reason="Reason.",
        related_topics=[],
        related_classes=[],
    )
    session.add(score)
    session.flush()
    return event


def test_overview_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "No high-signal events detected in the last 7 days." in response.text


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

    # These events carry no articles, so they only appear under "all time" --
    # the default 30-day window requires a dated article to match.
    first_page = client.get("/radar?date=all")
    assert first_page.status_code == 200
    assert "Page 1 of 2" in first_page.text

    second_page = client.get("/radar?date=all&page=2")
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
    assert (
        seeded["published_at"]
        .astimezone(ZoneInfo("America/Argentina/Buenos_Aires"))
        .strftime("%H:%M")
        in response.text
    )


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


# --- V1.1: Overview "High Signal · Last 7 Days" recency semantics ---------


def test_overview_shows_event_from_two_days_ago(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Recent Two Days Ago",
            published_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "Recent Two Days Ago" in response.text


def test_overview_hides_event_from_twenty_days_ago(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Old Twenty Days Ago",
            published_at=datetime.now(UTC) - timedelta(days=20),
        )
        session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "Old Twenty Days Ago" not in response.text
    assert "No high-signal events detected in the last 7 days." in response.text


def test_overview_ignores_recent_first_seen_with_old_published_at(client, db_session_factory):
    """Guards against the exact bootstrap bug this V1.1 pass fixes: an event
    re-touched today (first_seen_at now) but published in 2024 must not look
    like current signal."""
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Bootstrap Historical Event",
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
            first_seen_at=datetime.now(UTC),
        )
        session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "Bootstrap Historical Event" not in response.text
    assert "No high-signal events detected in the last 7 days." in response.text


def test_overview_empty_state_with_only_historical_data(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Ancient Event",
            published_at=datetime.now(UTC) - timedelta(days=400),
        )
        session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "Ancient Event" not in response.text
    assert "No high-signal events detected in the last 7 days." in response.text


# --- V1.1: Radar default window, `date` param, historical badge -----------


def test_radar_default_is_30_days(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Within Thirty Days",
            published_at=datetime.now(UTC) - timedelta(days=10),
        )
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Beyond Thirty Days",
            published_at=datetime.now(UTC) - timedelta(days=40),
        )
        session.commit()

    response = client.get("/radar")
    assert response.status_code == 200
    assert "Within Thirty Days" in response.text
    assert "Beyond Thirty Days" not in response.text


def test_radar_date_all_shows_historical(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Beyond Thirty Days All",
            published_at=datetime.now(UTC) - timedelta(days=40),
        )
        session.commit()

    response = client.get("/radar?date=all")
    assert response.status_code == 200
    assert "Beyond Thirty Days All" in response.text


def test_radar_date_7d_filters_correctly(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Within Seven Days",
            published_at=datetime.now(UTC) - timedelta(days=3),
        )
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Ten Days Old",
            published_at=datetime.now(UTC) - timedelta(days=10),
        )
        session.commit()

    response = client.get("/radar?date=7d")
    assert response.status_code == 200
    assert "Within Seven Days" in response.text
    assert "Ten Days Old" not in response.text


def test_radar_legacy_days_param_still_works(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Legacy Days Param Event",
            published_at=datetime.now(UTC) - timedelta(days=2),
        )
        session.commit()

    response = client.get("/radar?days=7")
    assert response.status_code == 200
    assert "Legacy Days Param Event" in response.text


def test_radar_historical_badge_shown_only_when_relevant(client, db_session_factory):
    with db_session_factory() as session:
        source, profile = _make_source_and_profile(session)
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Fresh Event",
            published_at=datetime.now(UTC) - timedelta(days=5),
        )
        _seed_event(
            session,
            source=source,
            profile=profile,
            title="Aged Event",
            published_at=datetime.now(UTC) - timedelta(days=45),
        )
        session.commit()

    # Default (30 days): "Aged Event" isn't shown at all, so no badge is possible.
    default_response = client.get("/radar")
    assert "Aged Event" not in default_response.text
    assert "Historical" not in default_response.text

    # 90 days: both show; only the >30-day-old one carries the badge.
    ninety_response = client.get("/radar?date=90d")
    assert "Fresh Event" in ninety_response.text
    assert "Aged Event" in ninety_response.text
    assert ninety_response.text.count("Historical") == 1

    # 7 days: only the fresh event qualifies, and it must not be historical.
    seven_response = client.get("/radar?date=7d")
    assert "Fresh Event" in seven_response.text
    assert "Historical" not in seven_response.text


# --- V1.1: relative_time helper --------------------------------------------


def test_relative_time_minutes():
    assert relative_time(datetime.now(UTC) - timedelta(minutes=12)) == "12 min ago"


def test_relative_time_hours():
    assert relative_time(datetime.now(UTC) - timedelta(hours=2, minutes=5)) == "2h ago"


def test_relative_time_days():
    assert relative_time(datetime.now(UTC) - timedelta(days=3, hours=1)) == "3d ago"


def test_relative_time_timezone_naive_treated_as_utc():
    naive = (datetime.now(UTC) - timedelta(minutes=30)).replace(tzinfo=None)
    assert relative_time(naive) == "30 min ago"


def test_relative_time_none():
    assert relative_time(None) == "—"


def test_overview_shows_relative_last_scan(client, seeded):
    response = client.get("/")
    assert response.status_code == 200
    assert "min ago" in response.text


# --- V1.1: KPI cards are real links -----------------------------------------


def test_overview_kpi_links(client, seeded):
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert f'href="/runs/{seeded["run_id"]}"' in body
    assert "/radar?min_alert=90" in body
    assert "date=30d" in body


# --- V1.1: width/density and sidebar icons ----------------------------------


def test_main_narrow_applied_to_overview_sources_runs_but_not_radar(client, seeded):
    for path in ("/", "/sources", "/runs", f"/runs/{seeded['run_id']}"):
        response = client.get(path)
        assert "main-narrow" in response.text

    radar_response = client.get("/radar")
    assert "main-narrow" not in radar_response.text

    detail_response = client.get(f"/radar/{seeded['event_id']}")
    assert "main-narrow" not in detail_response.text


def test_sidebar_uses_svg_icons(client):
    response = client.get("/")
    assert 'class="nav-icon"' in response.text
    assert "nav-dot" not in response.text

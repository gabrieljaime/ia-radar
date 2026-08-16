from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.db.models import Article, Event, EventScore, PipelineRun, Profile, Source
from scripts.show_latest_run import render_run


def add_run(session, *, started_at, with_event=True):
    run = PipelineRun(
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=2),
        status="completed",
        collected=1,
        analyzed=int(with_event),
        llm_calls=int(with_event),
        input_tokens=100,
        output_tokens=50,
        discard_counts={"too_old": 2},
    )
    session.add(run)
    session.flush()
    if not with_event:
        session.commit()
        return run
    source = Source(
        name="Official Source",
        source_type="rss",
        base_url=f"https://feed.example/{run.id}",
        trust_level=100,
        is_primary=True,
    )
    event = Event(
        analyzed_run_id=run.id,
        event_hash=uuid4().hex,
        normalized_title="agent observability",
        title="Agent Observability",
        status="analyzed",
        confidence=0.95,
        hype_probability=0.2,
    )
    session.add_all([source, event])
    session.flush()
    session.add(
        Article(
            event_id=event.id,
            source_id=source.id,
            canonical_url=f"https://article.example/{run.id}",
            normalized_title=event.normalized_title,
            title=event.title,
            summary_raw="summary",
            published_at=started_at,
            content_hash=uuid4().hex,
        )
    )
    for slug, relevance, alert in (
        ("educator", 40, 30),
        ("course", 95, 84),
        ("bank", 78, 70),
    ):
        profile = session.scalar(select(Profile).where(Profile.slug == slug))
        if profile is None:
            profile = Profile(slug=slug, name=slug.title())
            session.add(profile)
            session.flush()
        session.add(
            EventScore(
                event_id=event.id,
                profile_id=profile.id,
                relevance_score=relevance,
                alert_score=alert,
                novelty_score=82,
                actionability_score=90,
                strategic_impact_score=85,
                relevance_reason=f"Reason for {slug}",
                suggested_action=f"Action for {slug}",
                related_topics=["agents"],
                related_classes=[11] if slug == "course" else [],
            )
        )
    session.commit()
    return run


def test_latest_run_and_summary_show_three_profiles(session):
    now = datetime.now(UTC)
    old = add_run(session, started_at=now - timedelta(hours=1))
    latest = add_run(session, started_at=now)
    code, output = render_run(session)
    assert code == 0
    assert str(latest.id) in output
    assert str(old.id) not in output
    assert all(header in output for header in ("EDU_REL", "COUR_REL", "BANK_REL"))
    assert "95" in output and "84" in output


def test_specific_run_and_details(session):
    run = add_run(session, started_at=datetime.now(UTC))
    code, output = render_run(session, run_id=run.id, details=True)
    assert code == 0
    assert "COURSE" in output
    assert "relevance: 95" in output
    assert "alert: 84" in output
    assert "actionability: 90" in output
    assert "related_classes: 11" in output


def test_run_without_events_is_clear(session):
    run = add_run(session, started_at=datetime.now(UTC), with_event=False)
    code, output = render_run(session, run_id=run.id)
    assert code == 0
    assert f"Run {run.id} contains no analyzed events." in output


def test_missing_run_id_returns_nonzero(session):
    missing = uuid4()
    code, output = render_run(session, run_id=missing)
    assert code == 1
    assert f"Pipeline run {missing} not found." == output


def test_no_runs_is_not_an_error(session):
    assert render_run(session) == (0, "No pipeline runs found.")

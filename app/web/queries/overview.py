from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.db.models import Article, Event, EventScore, PipelineRun, Profile, Source, SourceHealth

RADAR_INTERVAL = timedelta(hours=2)
STALE_RUN_AFTER = RADAR_INTERVAL * 3


def _as_utc(value: datetime) -> datetime:
    # SQLite (used in tests) drops tzinfo on round-trip even for
    # DateTime(timezone=True) columns; Postgres (production) does not.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(slots=True)
class StatusItem:
    name: str
    state: str  # "ok" | "warning" | "error"
    detail: str


@dataclass(slots=True)
class HighSignalEvent:
    event: Event
    source_name: str | None
    published_at: datetime | None
    top_profile: str | None
    relevance: int | None
    alert: int | None
    confidence: float


@dataclass(slots=True)
class SourceHealthSummary:
    total: int
    healthy: int
    stale: int
    error: int
    unknown: int


def get_latest_run(session: Session) -> PipelineRun | None:
    return session.scalar(select(PipelineRun).order_by(desc(PipelineRun.started_at)).limit(1))


def get_source_health_summary(session: Session) -> SourceHealthSummary:
    sources = session.scalars(select(Source).where(Source.enabled.is_(True))).all()
    health_by_source = {
        health.source_id: health for health in session.scalars(select(SourceHealth)).all()
    }
    healthy = stale = error = unknown = 0
    for source in sources:
        health = health_by_source.get(source.id)
        if health is None:
            unknown += 1
        elif health.status == "OK":
            healthy += 1
        elif health.status == "STALE":
            stale += 1
        else:
            error += 1
    return SourceHealthSummary(len(sources), healthy, stale, error, unknown)


def get_system_status(
    session: Session, run: PipelineRun | None, source_summary: SourceHealthSummary
) -> list[StatusItem]:
    items = [StatusItem("API", "ok", "Responding")]
    try:
        session.execute(text("SELECT 1"))
        items.append(StatusItem("PostgreSQL", "ok", "Connected"))
    except Exception:
        items.append(StatusItem("PostgreSQL", "error", "Connection failed"))

    if source_summary.total == 0:
        items.append(StatusItem("Sources", "warning", "No sources configured"))
    elif source_summary.error > 0:
        items.append(StatusItem("Sources", "error", f"{source_summary.error} failing"))
    elif source_summary.stale > 0 or source_summary.unknown > 0:
        items.append(
            StatusItem(
                "Sources",
                "warning",
                f"{source_summary.stale} stale · {source_summary.unknown} unchecked",
            )
        )
    else:
        items.append(StatusItem("Sources", "ok", f"{source_summary.healthy} healthy"))

    running_for = datetime.now(UTC) - _as_utc(run.started_at) if run else timedelta(0)
    if run is None:
        items.append(StatusItem("Last Radar Run", "warning", "No runs yet"))
    elif run.status == "completed_with_errors":
        items.append(StatusItem("Last Radar Run", "warning", "Completed with errors"))
    elif run.finished_at is None and running_for > timedelta(hours=1):
        items.append(StatusItem("Last Radar Run", "error", "Run appears stuck"))
    elif run.finished_at is None:
        items.append(StatusItem("Last Radar Run", "ok", "Running"))
    elif datetime.now(UTC) - _as_utc(run.finished_at) > STALE_RUN_AFTER:
        items.append(StatusItem("Last Radar Run", "warning", "No recent run"))
    else:
        items.append(StatusItem("Last Radar Run", "ok", "Completed"))
    return items


def get_high_signal_events(session: Session, limit: int = 5) -> list[HighSignalEvent]:
    cutoff = datetime.now(UTC) - timedelta(days=14)
    rows = session.execute(
        select(Event, func.max(EventScore.alert_score).label("max_alert"))
        .join(EventScore, EventScore.event_id == Event.id)
        .where(Event.status == "analyzed", Event.last_seen_at >= cutoff)
        .group_by(Event.id)
        .order_by(desc("max_alert"), desc(Event.last_seen_at))
        .limit(limit)
    ).all()
    results = []
    for event, _max_alert in rows:
        article = session.scalar(
            select(Article)
            .where(Article.event_id == event.id)
            .order_by(desc(Article.published_at))
            .limit(1)
        )
        source = session.get(Source, article.source_id) if article else None
        top = session.execute(
            select(Profile, EventScore)
            .join(EventScore, EventScore.profile_id == Profile.id)
            .where(EventScore.event_id == event.id)
            .order_by(desc(EventScore.alert_score))
            .limit(1)
        ).first()
        profile, score = top if top else (None, None)
        results.append(
            HighSignalEvent(
                event=event,
                source_name=source.name if source else None,
                published_at=article.published_at if article else None,
                top_profile=profile.name if profile else None,
                relevance=score.relevance_score if score else None,
                alert=score.alert_score if score else None,
                confidence=event.confidence,
            )
        )
    return results

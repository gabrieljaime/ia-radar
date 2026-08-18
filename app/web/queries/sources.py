from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Article, Source, SourceHealth

_HEALTH_STATE = {
    "OK": "healthy",
    "STALE": "stale",
}


@dataclass(slots=True)
class SourceRow:
    source: Source
    health: SourceHealth | None
    last_fetch_at: datetime | None
    latest_published_at: datetime | None

    @property
    def status_label(self) -> str:
        if not self.source.enabled:
            return "disabled"
        if self.health is None:
            return "unknown"
        return _HEALTH_STATE.get(self.health.status, "error")


def list_sources_with_health(session: Session) -> list[SourceRow]:
    sources = session.scalars(select(Source).order_by(Source.source_type, Source.name)).all()
    health_by_source = {
        health.source_id: health for health in session.scalars(select(SourceHealth)).all()
    }
    stats = session.execute(
        select(
            Article.source_id,
            func.max(Article.discovered_at).label("last_fetch_at"),
            func.max(Article.published_at).label("latest_published_at"),
        ).group_by(Article.source_id)
    ).all()
    stats_by_source = {row.source_id: row for row in stats}

    rows = []
    for source in sources:
        stat = stats_by_source.get(source.id)
        rows.append(
            SourceRow(
                source=source,
                health=health_by_source.get(source.id),
                last_fetch_at=stat.last_fetch_at if stat else None,
                latest_published_at=stat.latest_published_at if stat else None,
            )
        )
    return rows

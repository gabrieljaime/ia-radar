from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Event, PipelineRun
from app.web.queries.events import EventListItem, build_list_item

DEFAULT_PAGE_SIZE = 25


@dataclass(slots=True)
class RunListPage:
    items: list[PipelineRun]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


def run_duration(run: PipelineRun) -> timedelta | None:
    if run.finished_at is None:
        return None
    return run.finished_at - run.started_at


def list_runs(
    session: Session, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> RunListPage:
    total = session.scalar(select(func.count()).select_from(PipelineRun)) or 0
    runs = session.scalars(
        select(PipelineRun)
        .order_by(desc(PipelineRun.started_at))
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return RunListPage(items=list(runs), page=page, page_size=page_size, total=total)


@dataclass(slots=True)
class RunDetail:
    run: PipelineRun
    duration: timedelta | None
    cost_configured: bool
    events: list[EventListItem]


def get_run_detail(session: Session, run_id: UUID, settings: Settings) -> RunDetail | None:
    run = session.get(PipelineRun, run_id)
    if run is None:
        return None
    events = session.scalars(
        select(Event).where(Event.analyzed_run_id == run_id).order_by(desc(Event.last_seen_at))
    ).all()
    cost_configured = bool(
        settings.llm_input_cost_per_million_usd or settings.llm_output_cost_per_million_usd
    )
    return RunDetail(
        run=run,
        duration=run_duration(run),
        cost_configured=cost_configured,
        events=[build_list_item(session, event) for event in events],
    )

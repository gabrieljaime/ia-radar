from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.web.context import sidebar_context
from app.web.deps import get_session
from app.web.queries import overview as queries
from app.web.templates import templates

router = APIRouter()


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    run = queries.get_latest_run(session)
    source_summary = queries.get_source_health_summary(session)
    status_items = queries.get_system_status(session, run, source_summary)
    high_signal_events = queries.get_high_signal_events(session)
    return templates.TemplateResponse(
        request,
        "overview/index.html",
        {
            "active_nav": "overview",
            "run": run,
            "status_items": status_items,
            "source_summary": source_summary,
            "high_signal_events": high_signal_events,
            **sidebar_context(session, status_items),
        },
    )

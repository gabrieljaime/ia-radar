from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.web.context import sidebar_context
from app.web.deps import get_session
from app.web.queries import events as queries
from app.web.templates import templates

router = APIRouter()


def _parse_filters(request: Request) -> queries.EventFilters:
    params = request.query_params
    source_id = params.get("source")
    return queries.EventFilters(
        profile=params.get("profile") or None,
        source_id=UUID(source_id) if source_id else None,
        days=int(params["days"]) if params.get("days") else None,
        primary_only={"true": True, "false": False}.get(params.get("primary")),
        min_relevance=int(params["min_relevance"]) if params.get("min_relevance") else None,
        min_alert=int(params["min_alert"]) if params.get("min_alert") else None,
        search=params.get("search") or None,
    )


@router.get("/radar")
def index(request: Request, session: Session = Depends(get_session)):
    filters = _parse_filters(request)
    page = max(1, int(request.query_params.get("page", 1)))
    result = queries.list_events(session, filters, page=page)
    filter_qs = urlencode({k: v for k, v in request.query_params.items() if k != "page"})
    context = {
        "active_nav": "radar",
        "result": result,
        "filters": filters,
        "profiles": queries.list_enabled_profiles(session),
        "sources": queries.list_filterable_sources(session),
        "filter_qs": filter_qs,
    }
    is_htmx = bool(request.headers.get("HX-Request"))
    if not is_htmx:
        context.update(sidebar_context(session))
    template = "radar/_list.html" if is_htmx else "radar/index.html"
    return templates.TemplateResponse(request, template, context)


@router.get("/radar/{event_id}")
def detail(event_id: UUID, request: Request, session: Session = Depends(get_session)):
    event_detail = queries.get_event_detail(session, event_id)
    if event_detail is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return templates.TemplateResponse(
        request,
        "radar/detail.html",
        {"active_nav": "radar", "detail": event_detail, **sidebar_context(session)},
    )

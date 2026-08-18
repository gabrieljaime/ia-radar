from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.web.context import sidebar_context
from app.web.deps import get_session
from app.web.queries import runs as queries
from app.web.templates import templates

router = APIRouter()


@router.get("/runs")
def index(request: Request, session: Session = Depends(get_session)):
    page = max(1, int(request.query_params.get("page", 1)))
    result = queries.list_runs(session, page=page)
    return templates.TemplateResponse(
        request,
        "runs/index.html",
        {"active_nav": "runs", "result": result, **sidebar_context(session)},
    )


@router.get("/runs/{run_id}")
def detail(run_id: UUID, request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    run_detail = queries.get_run_detail(session, run_id, settings)
    if run_detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request,
        "runs/detail.html",
        {"active_nav": "runs", "detail": run_detail, **sidebar_context(session)},
    )

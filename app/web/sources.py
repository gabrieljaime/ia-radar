from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.web.context import sidebar_context
from app.web.deps import get_session
from app.web.queries import sources as queries
from app.web.templates import templates

router = APIRouter()


@router.get("/sources")
def index(request: Request, session: Session = Depends(get_session)):
    rows = queries.list_sources_with_health(session)
    return templates.TemplateResponse(
        request,
        "sources/index.html",
        {"active_nav": "sources", "rows": rows, **sidebar_context(session)},
    )

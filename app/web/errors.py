import logging

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.web.templates import templates

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)
        return templates.TemplateResponse(
            request, "errors/500.html", {}, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        logger.exception("Unhandled error while serving %s", request.url.path)
        return templates.TemplateResponse(request, "errors/500.html", {}, status_code=500)

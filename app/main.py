from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_session_factory

app = FastAPI(title="AI Radar", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready(response: Response) -> dict[str, str]:
    settings = get_settings()
    try:
        with create_session_factory(settings.database_url)() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready"}
    return {"status": "ready"}

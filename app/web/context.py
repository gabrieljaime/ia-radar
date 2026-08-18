import os
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.web.queries.overview import (
    StatusItem,
    get_latest_run,
    get_source_health_summary,
    get_system_status,
)

_STATE_RANK = {"ok": 0, "warning": 1, "error": 2}
_STATE_LABEL = {"ok": "Operational", "warning": "Degraded", "error": "Error"}


def sidebar_context(session: Session, status_items: list[StatusItem] | None = None) -> dict:
    if status_items is None:
        run = get_latest_run(session)
        source_summary = get_source_health_summary(session)
        status_items = get_system_status(session, run, source_summary)
    worst = max((item.state for item in status_items), key=lambda state: _STATE_RANK[state])
    return {
        "system_state": worst,
        "system_label": _STATE_LABEL[worst],
        "app_version": os.environ.get("AI_RADAR_VERSION", "0.1.0"),
        "app_commit": os.environ.get("AI_RADAR_COMMIT"),
        "last_updated": datetime.now(UTC),
    }

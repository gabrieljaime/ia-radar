from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.web.tz import as_utc

# How far back "High Signal" on Overview looks.
RECENT_SIGNAL_DAYS = 7

# Radar's default view window, and the age past which an event visible in a
# wider window (90 days / all time) is marked "Historical" in the UI.
DEFAULT_RADAR_WINDOW_DAYS = 30
HISTORICAL_THRESHOLD_DAYS = 30

# Radar's `?date=` bucket -> lookback window in days. `all` has no lower bound.
DATE_RANGE_DAYS: dict[str, int | None] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}
DEFAULT_DATE_BUCKET = "30d"


def resolve_recency_at(published_at: datetime | None, first_seen_at: datetime) -> datetime:
    """The timestamp used to judge how recent an event is.

    published_at (from evidence articles) is authoritative. first_seen_at (when
    our pipeline first observed the event) is only a fallback for the rare
    event with no dated article, so a stale event can never look recent just
    because it was bootstrapped or re-seen recently.
    """
    return published_at if published_at is not None else first_seen_at


def is_historical(recency_at: datetime, *, threshold_days: int = HISTORICAL_THRESHOLD_DAYS) -> bool:
    return as_utc(recency_at) < datetime.now(UTC) - timedelta(days=threshold_days)

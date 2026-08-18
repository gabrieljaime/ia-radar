from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.web.tz import as_utc

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def to_local(value: datetime | None) -> str:
    """Render a UTC timestamp in the operator's local timezone.

    The database stores timestamps in UTC; the dashboard is a single-operator
    tool for America/Argentina/Buenos_Aires, so every timestamp shown to the
    user is converted here rather than left as raw UTC.
    """
    if value is None:
        return "—"
    return as_utc(value).astimezone(LOCAL_TZ).strftime("%d %b %Y · %H:%M")


def to_local_short(value: datetime | None) -> str:
    if value is None:
        return "—"
    return as_utc(value).astimezone(LOCAL_TZ).strftime("%d %b, %H:%M")


def relative_time(value: datetime | None) -> str:
    """Render "12 min ago" / "2h ago" / "3d ago" style relative timestamps.

    Centralized here so no template duplicates the minute/hour/day thresholds.
    """
    if value is None:
        return "—"
    seconds = int((datetime.now(UTC) - as_utc(value)).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"

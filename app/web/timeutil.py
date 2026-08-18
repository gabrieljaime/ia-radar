from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def _as_utc(value: datetime) -> datetime:
    # SQLite (used in tests) drops tzinfo on round-trip even for
    # DateTime(timezone=True) columns; Postgres (production) does not, so a
    # naive value here always represents UTC, never the host's local time.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def to_local(value: datetime | None) -> str:
    """Render a UTC timestamp in the operator's local timezone.

    The database stores timestamps in UTC; the dashboard is a single-operator
    tool for America/Argentina/Buenos_Aires, so every timestamp shown to the
    user is converted here rather than left as raw UTC.
    """
    if value is None:
        return "—"
    return _as_utc(value).astimezone(LOCAL_TZ).strftime("%d %b %Y · %H:%M")


def to_local_short(value: datetime | None) -> str:
    if value is None:
        return "—"
    return _as_utc(value).astimezone(LOCAL_TZ).strftime("%d %b, %H:%M")

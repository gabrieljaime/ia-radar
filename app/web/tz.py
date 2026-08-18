from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    """Normalize a possibly-naive datetime to UTC-aware.

    SQLite (used in tests) drops tzinfo on round-trip even for
    DateTime(timezone=True) columns; PostgreSQL (production) does not, so a
    naive value here always represents UTC, never the host's local time.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

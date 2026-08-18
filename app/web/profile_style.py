"""Deterministic color assignment for profile badges.

Profile names/slugs come from the DB/config, not hardcoded business logic —
this only maps whatever profiles exist today (or are added later) to one of
a fixed set of accent colors, keyed by a stable hash of the slug so the same
profile always gets the same color across renders.
"""

import zlib

_PALETTE = ["violet", "blue", "teal", "amber", "rose", "indigo"]


def profile_color(slug: str) -> str:
    return _PALETTE[zlib.crc32(slug.encode()) % len(_PALETTE)]

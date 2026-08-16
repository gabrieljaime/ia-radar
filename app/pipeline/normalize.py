import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.domain.models import Candidate, DiscardReason

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def normalize_title(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", html.unescape(title).lower()).split())


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalize_candidate(candidate: Candidate) -> Candidate:
    candidate.title = html.unescape(candidate.title).strip()
    candidate.summary = re.sub(r"<[^>]+>", " ", html.unescape(candidate.summary))
    candidate.summary = " ".join(candidate.summary.split())
    candidate.normalized_title = normalize_title(candidate.title)
    candidate.canonical_url = canonicalize_url(candidate.url)
    hash_input = candidate.summary.lower() if candidate.summary else candidate.normalized_title
    candidate.content_hash = hashlib.sha256(hash_input.encode()).hexdigest()
    if not candidate.normalized_title or not candidate.canonical_url.startswith(
        ("http://", "https://")
    ):
        candidate.discard_reason = DiscardReason.INVALID
    return candidate

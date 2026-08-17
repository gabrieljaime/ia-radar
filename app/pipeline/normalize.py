import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.domain.models import Candidate, DiscardReason

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
_ARTIFACT_VARIANTS = ("fp8", "bf16", "gguf", "awq", "gptq", "int8")


def normalize_title(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", html.unescape(title).lower()).split())


def base_model_identity(value: str) -> str | None:
    """Return a conservative family identity for known model-shaped identifiers."""
    compact = re.sub(r"(?i)new model repository:\s*[^/]+/", "", html.unescape(value))
    match = re.search(
        r"(?i)\b(qwen|glm|deepseek)[\s_-]*([0-9]+(?:\.[0-9]+)*)"
        r"(?:[\s_-]+([0-9]+(?:\.[0-9]+)?[bt](?:[\s_-]+a[0-9]+b)?))?",
        compact,
    )
    if not match:
        return None
    parts = [part.lower().replace(" ", "-").replace("_", "-") for part in match.groups() if part]
    identity = "-".join(parts)
    identity = re.sub(rf"-(?:{'|'.join(_ARTIFACT_VARIANTS)})$", "", identity)
    return identity


def strip_artifact_variant(model_id: str) -> str:
    return re.sub(rf"(?i)(?:[-_](?:{'|'.join(_ARTIFACT_VARIANTS)}))$", "", model_id.strip())


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

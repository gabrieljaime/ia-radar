import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.domain.models import Candidate, DiscardReason

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
_TUNE_VARIANTS = ("instruct", "chat", "base")
_MODEL_FAMILY_PATTERN = re.compile(
    r"(?i)\b(qwen|glm|deepseek)[\s_-]*([0-9]+(?:\.[0-9]+)*)"
    r"(?:[\s_-]+([0-9]+(?:\.[0-9]+)?[bt](?:[\s_-]+a[0-9]+b)?))?"
    r"(?:[\s_-]+([a-z][a-z0-9]*))?"
)
_COMMAND_FAMILY_PATTERN = re.compile(
    r"(?i)\b(command)[\s_-]+(a|r\+|r)(?!\w)"
    r"(?:[\s_-]+(vision|reasoning|[0-9]+b))?"
    r"(?:[\s_-]+([a-z][a-z0-9]*))?"
)


def normalize_title(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", html.unescape(title).lower()).split())


def base_model_identity(value: str) -> str | None:
    """Return a conservative family identity for known model-shaped identifiers.

    Quantization/artifact qualifiers (FP8, GGUF, ...) are ignored so those
    releases collapse into one identity. Tuning qualifiers (Instruct, Chat,
    Base) are distinct, newsworthy releases, so they stay separate
    identities instead of collapsing into the base model's identity.
    """
    compact = re.sub(r"(?i)new model repository:\s*[^/]+/", "", html.unescape(value))
    match = _MODEL_FAMILY_PATTERN.search(compact)
    if match:
        vendor, version, size, qualifier = match.groups()
        parts = [vendor, version, size]
    else:
        match = _COMMAND_FAMILY_PATTERN.search(compact)
        if not match:
            return None
        vendor, variant, subvariant, qualifier = match.groups()
        parts = [vendor, variant, subvariant]
    identity = "-".join(part.lower().replace(" ", "-").replace("_", "-") for part in parts if part)
    if qualifier and qualifier.lower() in _TUNE_VARIANTS:
        identity = f"{identity}-{qualifier.lower()}"
    return identity


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

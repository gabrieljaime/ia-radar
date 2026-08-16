from app.domain.models import Candidate
from app.pipeline.normalize import canonicalize_url, normalize_candidate, normalize_title


def test_canonicalize_url_removes_tracking_and_fragment():
    assert canonicalize_url("HTTPS://Example.COM/news/?utm_source=x&id=3#part") == (
        "https://example.com/news?id=3"
    )


def test_normalize_title_and_content_hash():
    candidate = Candidate(
        "source",
        "https://feed",
        90,
        True,
        "  AI: Agents! ",
        "https://x/a",
        "<b>New</b> release",
        None,
    )
    result = normalize_candidate(candidate)
    assert normalize_title(candidate.title) == "ai agents"
    assert result.summary == "New release"
    assert len(result.content_hash) == 64

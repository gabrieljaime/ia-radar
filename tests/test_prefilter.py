from datetime import UTC, datetime, timedelta

from app.domain.models import Candidate, DiscardReason
from app.pipeline.normalize import normalize_candidate
from app.pipeline.prefilter import prefilter


def test_prefilter_records_too_old(profiles):
    item = Candidate(
        "Official",
        "https://example.com/feed",
        100,
        True,
        "AI agents release",
        "https://example.com/old",
        "tool calling",
        datetime.now(UTC) - timedelta(days=30),
    )
    assert prefilter(normalize_candidate(item), profiles, 48, 1) == DiscardReason.TOO_OLD


def test_prefilter_does_not_assume_missing_publication_is_recent(profiles):
    item = Candidate(
        "Official", "https://example.com/feed", 100, True, "AI release", "https://x.test", "", None
    )
    assert prefilter(normalize_candidate(item), profiles, 48, 0) == DiscardReason.INVALID


def test_prefilter_records_low_relevance(profiles):
    item = Candidate(
        "Official",
        "https://example.com/feed",
        100,
        True,
        "Cooking",
        "https://example.com/x",
        "Recipe",
        datetime.now(UTC),
    )
    assert prefilter(normalize_candidate(item), profiles, 14, 20) == DiscardReason.LOW_RELEVANCE


def test_prefilter_keeps_novel_model_from_high_trust_primary_source(profiles):
    item = Candidate(
        "Official",
        "https://example.com/feed",
        100,
        True,
        "Acme unveils Zeta",
        "https://example.com/zeta",
        "A new multimodal model is now available.",
        datetime.now(UTC),
    )
    assert prefilter(normalize_candidate(item), profiles, 14, 20) is None

from datetime import UTC, datetime, timedelta

from app.domain.models import Candidate, DiscardReason
from app.pipeline.normalize import normalize_candidate
from app.pipeline.prefilter import is_strategic_safety_signal, prefilter


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


def test_general_ai_profile_keeps_major_model_launch(profiles):
    general = [profile for profile in profiles if profile.slug == "general_ai"]
    item = Candidate(
        "Official",
        "https://example.com/feed",
        90,
        True,
        "OpenAI launches a new frontier model generation",
        "https://example.com/gpt-6",
        "Major reasoning, multimodal and context window improvements.",
        datetime.now(UTC),
    )
    assert prefilter(normalize_candidate(item), general, 48, 20) is None


def test_general_ai_profile_keeps_strategic_safety_statement(profiles):
    general = [profile for profile in profiles if profile.slug == "general_ai"]
    item = Candidate(
        "Trusted coverage",
        "https://example.com/feed",
        75,
        False,
        "Altman and Musk back Amodei's call for an AI slowdown",
        "https://example.com/pacing",
        "Frontier lab leaders support independent safety evaluations.",
        datetime.now(UTC),
        source_requires_primary_verification=True,
    )
    assert prefilter(normalize_candidate(item), general, 48, 20) is None
    assert is_strategic_safety_signal(item) is True


def test_extinction_probability_headline_is_strategic_safety_signal():
    item = Candidate(
        "Trusted coverage",
        "https://example.com/feed",
        75,
        False,
        "Ex-Anthropic researcher says there is a 10% chance AI could kill us all",
        "https://example.com/extinction-risk",
        "Evan Hubinger discussed risks from frontier AI systems.",
        datetime.now(UTC),
    )
    assert is_strategic_safety_signal(item) is True

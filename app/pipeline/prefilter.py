from datetime import UTC, datetime, timedelta

from app.domain.models import Candidate, DiscardReason
from app.profiles.models import ProfileConfig

_BROAD_AI_SIGNALS = {
    "ai",
    "artificial intelligence",
    "agent",
    "foundation model",
    "generative",
    "llm",
    "machine learning",
    "model",
    "multimodal",
}


def prefilter(
    candidate: Candidate,
    profiles: list[ProfileConfig],
    lookback_hours: int,
    min_score: int,
) -> DiscardReason | None:
    if candidate.discard_reason:
        return candidate.discard_reason
    if candidate.published_at is None:
        return DiscardReason.INVALID
    published_at = candidate.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    if published_at.astimezone(UTC) < datetime.now(UTC) - timedelta(hours=lookback_hours):
        return DiscardReason.TOO_OLD
    if candidate.source_trust < 40:
        return DiscardReason.LOW_TRUST
    text = f"{candidate.normalized_title} {candidate.summary.lower()}".replace("_", " ")
    weighted_matches = 0.0
    for profile in profiles:
        weighted_matches += sum(
            weight for topic, weight in profile.topics.items() if topic.replace("_", " ") in text
        )
        weighted_matches += sum(
            weight
            for entity, weight in profile.entities.items()
            if entity.lower().replace("_", " ") in text
        )
    heuristic_score = min(100, round(weighted_matches * 30))
    if heuristic_score < min_score:
        # Exact profile keywords are intentionally conservative, but a highly trusted primary
        # feed should not lose a major release merely because its product name is new to YAML.
        if (
            candidate.source_is_primary
            and candidate.source_trust >= 95
            and any(signal in text for signal in _BROAD_AI_SIGNALS)
        ):
            return None
        return DiscardReason.LOW_RELEVANCE
    return None

import re
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
    "new model",
    "model release",
    "new generation",
    "frontier model",
    "open weights",
    "api release",
    "breaking change",
    "reasoning",
    "tool calling",
    "computer use",
    "context window",
    "embedding",
    "inference",
    "deprecation",
    "general availability",
    "preview",
}

_LOW_VALUE_UPDATE_SIGNALS = {"documentation", "docs update", "typo", "minor fix"}

_WEB_ARTICLE_SIGNALS = {
    "agentic",
    "ai agent",
    "ai chip",
    "ai regulation",
    "ai safety",
    "benchmark",
    "coding agent",
    "computer use",
    "context window",
    "embedding",
    "gpu",
    "inference",
    "large language model",
    "llm",
    "mcp",
    "model release",
    "multimodal",
    "new model",
    "npu",
    "open weight",
    "post-training",
    "rag",
    "reasoning model",
    "reinforcement learning",
    "rerank",
    "tool calling",
}

_INFRASTRUCTURE_MAJOR_SIGNALS = {
    "breaking change",
    "new architecture",
    "new model",
    "quantization",
    "speculative decoding",
    "distributed serving",
    "gpu support",
    "performance improvement",
    "performance milestone",
}


def is_outside_lookback(candidate: Candidate, lookback_hours: int) -> bool:
    if candidate.published_at is None:
        return False
    published_at = candidate.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return published_at.astimezone(UTC) < datetime.now(UTC) - timedelta(hours=lookback_hours)


def is_primary_bypass(candidate: Candidate, profiles: list[ProfileConfig], min_score: int) -> bool:
    text = f"{candidate.normalized_title} {candidate.summary.lower()}".replace("_", " ")
    weighted_matches = sum(
        weight
        for profile in profiles
        for topic, weight in profile.topics.items()
        if topic.replace("_", " ") in text
    ) + sum(
        weight
        for profile in profiles
        for entity, weight in profile.entities.items()
        if entity.lower().replace("_", " ") in text
    )
    return (
        min(100, round(weighted_matches * 30)) < min_score
        and candidate.source_is_primary
        and candidate.source_trust >= 95
        and any(signal in text for signal in _BROAD_AI_SIGNALS)
    )


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
    if is_outside_lookback(candidate, lookback_hours):
        return DiscardReason.TOO_OLD
    if candidate.source_trust < 40:
        return DiscardReason.LOW_TRUST
    text = f"{candidate.normalized_title} {candidate.summary.lower()}".replace("_", " ")
    if candidate.source_type == "web_changelog" and any(
        signal in text for signal in _LOW_VALUE_UPDATE_SIGNALS
    ):
        return DiscardReason.LOW_RELEVANCE
    if candidate.source_type == "github_releases" and "vllm" in candidate.source_name.lower():
        patch_release = bool(re.search(r"\bv?\d+\.\d+\.[1-9]\d*\b", candidate.title.lower()))
        if patch_release and not any(signal in text for signal in _INFRASTRUCTURE_MAJOR_SIGNALS):
            return DiscardReason.LOW_RELEVANCE
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
        if candidate.source_type == "web_articles" and any(
            signal in text for signal in _WEB_ARTICLE_SIGNALS
        ):
            return None
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

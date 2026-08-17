from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DiscardReason(StrEnum):
    DUPLICATE = "duplicate"
    TOO_OLD = "too_old"
    LOW_RELEVANCE = "low_relevance"
    LOW_TRUST = "low_trust"
    HIGH_HYPE = "high_hype"
    ALREADY_SEEN = "already_seen"
    INVALID = "invalid"
    ANALYSIS_FAILED = "analysis_failed"


@dataclass(slots=True)
class Candidate:
    source_name: str
    source_url: str
    source_trust: int
    source_is_primary: bool
    title: str
    url: str
    summary: str
    published_at: datetime | None
    source_type: str = "rss"
    source_requires_primary_verification: bool = False
    external_id: str | None = None
    exact_model_id: str | None = None
    organization: str | None = None
    source_last_modified_at: datetime | None = None
    canonical_url: str = ""
    normalized_title: str = ""
    content_hash: str = ""
    discard_reason: DiscardReason | None = None


@dataclass(slots=True)
class StoredCandidate:
    candidate_record_id: UUID
    article_id: UUID
    event_id: UUID
    candidate: Candidate
    is_new_article: bool
    is_new_event: bool
    should_reanalyze: bool = False
    evidence_upgrade_reason: str | None = None


@dataclass(slots=True)
class PipelineResult:
    run_id: UUID | None
    skipped: bool = False
    collected: int = 0
    analyzed: int = 0
    alerts_sent: int = 0
    discarded: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    web_articles_sources_fetched: int = 0
    web_articles_items_found: int = 0
    web_articles_items_new: int = 0
    web_articles_prefilter_passed: int = 0
    candidates_new: int = 0
    prefilter_passed: int = 0
    primary_bypass_passed: int = 0
    pending_reanalysis: int = 0
    evidence_reanalysis: int = 0
    analysis_retries: int = 0
    llm_call_limit_reached: bool = False

    def record_discard(self, reason: DiscardReason) -> None:
        self.discarded[reason.value] = self.discarded.get(reason.value, 0) + 1

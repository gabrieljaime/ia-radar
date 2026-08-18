from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from rapidfuzz.fuzz import ratio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    Article,
    CandidateRecord,
    Event,
    EventScore,
    PipelineRun,
    Profile,
    Source,
)
from app.domain.models import Candidate, DiscardReason, PipelineResult, StoredCandidate
from app.llm.schemas import ArticleAnalysis
from app.pipeline.normalize import base_model_identity
from app.profiles.models import ProfileConfig


class RadarRepository:
    _ADVISORY_LOCK_KEY = 4_204_241_337

    def __init__(self, session: Session, title_threshold: float = 88.0):
        self.session = session
        self.title_threshold = title_threshold
        self._lock_connection = None

    def try_acquire_run_lock(self) -> bool:
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return True
        connection = bind.connect()
        acquired = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": self._ADVISORY_LOCK_KEY},
            )
        )
        if acquired:
            self._lock_connection = connection
        else:
            connection.close()
        return acquired

    def release_run_lock(self) -> None:
        if self._lock_connection is None:
            return
        try:
            self._lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": self._ADVISORY_LOCK_KEY},
            )
        finally:
            self._lock_connection.close()
            self._lock_connection = None

    def start_run(self) -> PipelineRun:
        run = PipelineRun()
        self.session.add(run)
        self.session.commit()
        return run

    def finish_run(self, result: PipelineResult) -> None:
        run = self.session.get(PipelineRun, result.run_id)
        if run is None:
            return
        run.status = "completed_with_errors" if result.errors else "completed"
        run.collected = result.collected
        run.analyzed = result.analyzed
        run.alerts_sent = result.alerts_sent
        run.llm_calls = result.llm_calls
        run.input_tokens = result.input_tokens
        run.output_tokens = result.output_tokens
        run.estimated_cost_usd = result.estimated_cost_usd
        run.candidates_new = result.candidates_new
        run.prefilter_passed = result.prefilter_passed
        run.primary_bypass_passed = result.primary_bypass_passed
        run.pending_reanalysis = result.pending_reanalysis
        run.evidence_reanalysis = result.evidence_reanalysis
        run.analysis_retries = result.analysis_retries
        run.llm_call_limit_reached = result.llm_call_limit_reached
        run.discard_counts = result.discarded
        run.error_summary = result.errors
        run.finished_at = datetime.now(UTC)
        self.session.commit()

    def store_candidate(self, candidate: Candidate) -> StoredCandidate:
        record = CandidateRecord(
            source_name=candidate.source_name,
            canonical_url=candidate.canonical_url,
            title=candidate.title,
        )
        self.session.add(record)
        self.session.flush()
        existing = self.session.scalar(
            select(Article).where(Article.canonical_url == candidate.canonical_url)
        )
        if existing:
            record.article_id = existing.id
            record.event_id = existing.event_id
            record.status = "discarded"
            record.discard_reason = DiscardReason.ALREADY_SEEN.value
            self.session.commit()
            return StoredCandidate(
                record.id, existing.id, existing.event_id, candidate, False, False
            )

        event = self._matching_event(candidate)
        is_new_event = event is None
        upgrade_reason = None
        if event is None:
            event = Event(
                event_hash=hashlib.sha256(candidate.normalized_title.encode()).hexdigest(),
                normalized_title=candidate.normalized_title,
                title=candidate.title,
                primary_source_verified=candidate.source_is_primary,
                primary_source_url=candidate.canonical_url if candidate.source_is_primary else None,
            )
            self.session.add(event)
            self.session.flush()
        else:
            event.last_seen_at = datetime.now(UTC)
            upgrade_reason = self._evidence_upgrade_reason(event, candidate)

        source = self._upsert_source(candidate)
        article = Article(
            event_id=event.id,
            source_id=source.id,
            external_id=candidate.external_id,
            canonical_url=candidate.canonical_url,
            normalized_title=candidate.normalized_title,
            title=candidate.title,
            summary_raw=candidate.summary,
            published_at=candidate.published_at,
            source_last_modified_at=candidate.source_last_modified_at,
            content_hash=candidate.content_hash,
            status="new"
            if is_new_event
            else ("evidence_upgrade" if upgrade_reason else "duplicate"),
            discard_reason=(
                DiscardReason.DUPLICATE.value if not is_new_event and not upgrade_reason else None
            ),
        )
        self.session.add(article)
        self.session.flush()
        record.article_id = article.id
        record.event_id = event.id
        if is_new_event:
            event.origin_article_id = article.id
        if source.is_primary and self._should_prefer_primary(event, source):
            event.primary_source_verified = True
            event.primary_source_url = candidate.canonical_url
        if upgrade_reason:
            event.evidence_upgrade_reason = upgrade_reason
            event.last_evidence_upgrade_at = datetime.now(UTC)
        record.status = "accepted" if is_new_event or upgrade_reason else "discarded"
        record.discard_reason = (
            DiscardReason.DUPLICATE.value if not is_new_event and not upgrade_reason else None
        )
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(Article).where(Article.canonical_url == candidate.canonical_url)
            )
            if existing is None:
                raise
            retry_record = CandidateRecord(
                article_id=existing.id,
                event_id=existing.event_id,
                source_name=candidate.source_name,
                canonical_url=candidate.canonical_url,
                title=candidate.title,
                status="discarded",
                discard_reason=DiscardReason.ALREADY_SEEN.value,
            )
            self.session.add(retry_record)
            self.session.commit()
            return StoredCandidate(
                retry_record.id, existing.id, existing.event_id, candidate, False, False
            )
        return StoredCandidate(
            record.id,
            article.id,
            event.id,
            candidate,
            True,
            is_new_event,
            should_reanalyze=bool(upgrade_reason),
            evidence_upgrade_reason=upgrade_reason,
        )

    def _should_prefer_primary(self, event: Event, candidate_source: Source) -> bool:
        if not event.primary_source_url:
            return True
        current_source = self.session.scalar(
            select(Source)
            .join(Article, Article.source_id == Source.id)
            .where(
                Article.event_id == event.id,
                Article.canonical_url == event.primary_source_url,
            )
            .limit(1)
        )
        if current_source is None:
            return True
        priorities = {
            "web_changelog": 50,
            "rss": 45,
            "web_articles": 40,
            "github_releases": 30,
            "huggingface_models": 30,
        }
        candidate_rank = (
            priorities.get(candidate_source.source_type, 0),
            candidate_source.trust_level,
        )
        current_rank = (priorities.get(current_source.source_type, 0), current_source.trust_level)
        return candidate_rank > current_rank

    def _evidence_upgrade_reason(self, event: Event, candidate: Candidate) -> str | None:
        if event.status == "pending":
            return "pending_event_new_evidence"
        if (
            event.discard_reason == DiscardReason.ANALYSIS_FAILED.value
            and candidate.source_is_primary
        ):
            return "retry_failed_with_primary"
        best_source = self.session.scalar(
            select(Source)
            .join(Article, Article.source_id == Source.id)
            .where(Article.event_id == event.id)
            .order_by(Source.is_primary.desc(), Source.trust_level.desc())
            .limit(1)
        )
        if best_source is None:
            return "first_material_evidence"
        if candidate.source_is_primary and not event.primary_source_verified:
            return "primary_source_discovered"
        if candidate.source_trust >= best_source.trust_level + 10:
            return "higher_trust_source"
        if event.confidence < 0.6 and (
            candidate.source_is_primary or candidate.source_trust > best_source.trust_level
        ):
            return "low_confidence_better_evidence"
        return None

    def _matching_event(self, candidate: Candidate) -> Event | None:
        # Very short boilerplate summaries (for example "Read more") are not reliable content.
        if len(candidate.summary) >= 40:
            exact_article = self.session.scalar(
                select(Article).where(Article.content_hash == candidate.content_hash).limit(1)
            )
            if exact_article is not None:
                return self.session.get(Event, exact_article.event_id)

        cutoff = datetime.now(UTC) - timedelta(days=14)
        events = self.session.scalars(select(Event).where(Event.first_seen_at >= cutoff)).all()
        candidate_model = (
            base_model_identity(candidate.exact_model_id) if candidate.exact_model_id else None
        )
        if candidate_model:
            model_match = next(
                (
                    event
                    for event in events
                    if base_model_identity(event.subject_name or event.title) == candidate_model
                ),
                None,
            )
            if model_match is not None:
                return model_match
        return next(
            (
                event
                for event in events
                if ratio(event.normalized_title, candidate.normalized_title) >= self.title_threshold
            ),
            None,
        )

    def _upsert_source(self, candidate: Candidate) -> Source:
        source = self.session.scalar(
            select(Source).where(
                Source.source_type == candidate.source_type,
                Source.base_url == candidate.source_url,
            )
        )
        if source is None:
            source = Source(
                name=candidate.source_name,
                source_type=candidate.source_type,
                base_url=candidate.source_url,
                trust_level=candidate.source_trust,
                is_primary=candidate.source_is_primary,
                requires_primary_verification=candidate.source_requires_primary_verification,
            )
            self.session.add(source)
            self.session.flush()
        else:
            source.name = candidate.source_name
            source.trust_level = candidate.source_trust
            source.is_primary = candidate.source_is_primary
            source.requires_primary_verification = candidate.source_requires_primary_verification
        return source

    def sync_profiles(self, profiles: list[ProfileConfig]) -> dict[str, Profile]:
        result = {}
        configured_slugs = {config.slug for config in profiles}
        for stored_profile in self.session.scalars(select(Profile)).all():
            if stored_profile.slug not in configured_slugs:
                stored_profile.enabled = False
        for config in profiles:
            profile = self.session.scalar(select(Profile).where(Profile.slug == config.slug))
            if profile is None:
                profile = Profile(
                    slug=config.slug,
                    name=config.name,
                    icon=config.icon,
                    enabled=config.enabled,
                )
                self.session.add(profile)
                self.session.flush()
            else:
                profile.name = config.name
                profile.icon = config.icon
                profile.enabled = config.enabled
            result[config.slug] = profile
        self.session.commit()
        return result

    def event_needs_analysis(self, event_id: UUID) -> bool:
        event = self.session.get(Event, event_id)
        return event is not None and event.status == "pending"

    def save_analysis(
        self,
        run_id: UUID,
        event_id: UUID,
        article_id: UUID,
        evidence_upgrade_reason: str | None,
        analysis: ArticleAnalysis,
        profiles: dict[str, Profile],
        final_scores: dict[str, int],
    ) -> None:
        event = self.session.get(Event, event_id)
        if event is None:
            raise LookupError(f"Unknown event: {event_id}")
        event.subject_name = analysis.subject_name
        event.summary = analysis.summary
        event.what_happened = analysis.what_happened
        event.why_it_matters = analysis.why_it_matters
        event.what_changed = analysis.what_changed
        event.novelty_score = analysis.novelty_score
        event.credibility_score = analysis.credibility_score
        event.confidence = analysis.confidence
        event.hype_probability = analysis.hype_probability
        event.analyzed_run_id = run_id
        event.analysis_article_id = article_id
        event.analysis_count += 1
        if evidence_upgrade_reason:
            event.evidence_upgrade_reason = evidence_upgrade_reason
            event.last_evidence_upgrade_at = datetime.now(UTC)
        event.status = "analyzed"
        for evaluation in analysis.profiles:
            profile = profiles.get(evaluation.profile)
            if profile is None:
                continue
            score = self.session.scalar(
                select(EventScore).where(
                    EventScore.event_id == event_id, EventScore.profile_id == profile.id
                )
            )
            if score is None:
                score = EventScore(event_id=event_id, profile_id=profile.id)
                self.session.add(score)
            score.relevance_score = evaluation.relevance_score
            score.novelty_score = evaluation.novelty_score
            score.actionability_score = evaluation.actionability_score
            score.strategic_impact_score = evaluation.strategic_impact_score
            score.alert_score = final_scores[evaluation.profile]
            score.relevance_reason = evaluation.reason
            score.suggested_action = evaluation.suggested_action
            score.related_topics = evaluation.related_topics
            score.related_classes = evaluation.related_classes
        self.session.commit()

    def mark_analysis_failed(self, candidate_record_id: UUID, event_id: UUID) -> None:
        event = self.session.get(Event, event_id)
        if event:
            event.status = "discarded"
            event.discard_reason = DiscardReason.ANALYSIS_FAILED.value
        self._mark_candidate_record(candidate_record_id, DiscardReason.ANALYSIS_FAILED)
        self.session.commit()

    def mark_discard(
        self, candidate_record_id: UUID, article_id: UUID, event_id: UUID, reason: DiscardReason
    ) -> None:
        article = self.session.get(Article, article_id)
        event = self.session.get(Event, event_id)
        if article:
            article.status = "discarded"
            article.discard_reason = reason.value
        if event and reason != DiscardReason.DUPLICATE:
            event.status = "discarded"
            event.discard_reason = reason.value
        self._mark_candidate_record(candidate_record_id, reason)
        self.session.commit()

    def mark_too_old(
        self, candidate_record_id: UUID, article_id: UUID, event_id: UUID, *, new_event: bool
    ) -> None:
        article = self.session.get(Article, article_id)
        if article:
            article.status = "discarded"
            article.discard_reason = DiscardReason.TOO_OLD.value
        if new_event:
            event = self.session.get(Event, event_id)
            if event:
                event.status = "discarded"
                event.discard_reason = DiscardReason.TOO_OLD.value
        self._mark_candidate_record(candidate_record_id, DiscardReason.TOO_OLD)
        self.session.commit()

    def _mark_candidate_record(self, record_id: UUID, reason: DiscardReason) -> None:
        record = self.session.get(CandidateRecord, record_id)
        if record:
            record.status = "discarded"
            record.discard_reason = reason.value

    def reserve_alert(self, event_id: UUID, content_fingerprint: str) -> Alert | None:
        existing = self.session.scalar(
            select(Alert).where(
                Alert.event_id == event_id,
                Alert.alert_type == "immediate",
                Alert.channel == "telegram",
            )
        )
        if existing:
            return None
        alert = Alert(event_id=event_id, content_fingerprint=content_fingerprint)
        self.session.add(alert)
        try:
            self.session.commit()
        except IntegrityError:
            # A concurrent run may have reserved the same event after our SELECT.
            self.session.rollback()
            return None
        return alert

    def mark_alert_sent(self, alert_id: UUID, provider_message_id: str) -> None:
        alert = self.session.get(Alert, alert_id)
        if alert:
            alert.delivery_status = "sent"
            alert.provider_message_id = provider_message_id
            alert.sent_at = datetime.now(UTC)
            self.session.commit()

    def mark_alert_failed(self, alert_id: UUID, error_code: str) -> None:
        alert = self.session.get(Alert, alert_id)
        if alert:
            alert.delivery_status = "failed"
            alert.error_code = error_code[:100]
            self.session.commit()

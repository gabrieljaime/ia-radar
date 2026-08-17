from __future__ import annotations

import hashlib
import logging

from app.alerts.base import AlertChannel
from app.alerts.formatting import format_telegram_alert
from app.collectors.base import Collector
from app.db.repository import RadarRepository
from app.domain.models import DiscardReason, PipelineResult
from app.llm.base import LLMProvider
from app.llm.provider import LLMRequestError, StructuredOutputError
from app.pipeline.normalize import normalize_candidate
from app.pipeline.prefilter import prefilter
from app.pipeline.score import calculate_scores
from app.profiles.models import ProfileConfig

logger = logging.getLogger(__name__)


def validate_factual_anchors(candidate, analysis) -> None:
    if not candidate.exact_model_id:
        return
    expected = candidate.exact_model_id.casefold().strip()
    returned = analysis.subject_name.casefold().strip()
    if returned not in {expected, expected.rsplit("/", 1)[-1]}:
        raise StructuredOutputError(
            f"LLM subject_name contradicts exact_model_id {candidate.exact_model_id}"
        )


class RadarService:
    def __init__(
        self,
        collector: Collector,
        llm: LLMProvider | None,
        repository: RadarRepository,
        profiles: list[ProfileConfig],
        alert_channel: AlertChannel | None,
        lookback_hours: int = 48,
        prefilter_min_score: int = 20,
        alert_score_threshold: int = 90,
        alert_confidence_threshold: float = 0.75,
    ):
        self.collector = collector
        self.llm = llm
        self.repository = repository
        self.profiles = profiles
        self.enabled_profiles = [profile for profile in profiles if profile.enabled]
        if not self.enabled_profiles:
            raise ValueError("At least one profile must be enabled")
        self.alert_channel = alert_channel
        self.lookback_hours = lookback_hours
        self.prefilter_min_score = prefilter_min_score
        self.alert_score_threshold = alert_score_threshold
        self.alert_confidence_threshold = alert_confidence_threshold

    async def run(self) -> PipelineResult:
        if not self.repository.try_acquire_run_lock():
            logger.info("radar_run_skipped_already_running")
            return PipelineResult(run_id=None, skipped=True)
        try:
            run = self.repository.start_run()
            result = PipelineResult(run_id=run.id)
            profile_rows = self.repository.sync_profiles(self.profiles)
            try:
                candidates = await self.collector.collect()
                result.collected = len(candidates)
                result.errors.extend(getattr(self.collector, "errors", []))
                for child in getattr(self.collector, "collectors", []):
                    if getattr(child, "metrics", None) is not None:
                        result.web_articles_sources_fetched += child.metrics["sources_fetched"]
                        result.web_articles_items_found += child.metrics["items_found"]
                for raw_candidate in candidates:
                    try:
                        await self._process_candidate(raw_candidate, profile_rows, result)
                    except Exception as error:  # isolate one candidate from the rest of the run
                        logger.exception(
                            "candidate_processing_failed",
                            extra={"run_id": str(run.id), "error_type": type(error).__name__},
                        )
                        result.errors.append(f"candidate: {type(error).__name__}")
            finally:
                self.repository.finish_run(result)
                logger.info(
                    "radar_run_completed",
                    extra={
                        "run_id": str(run.id),
                        "articles_found": result.collected,
                        "articles_analyzed": result.analyzed,
                        "alerts_sent": result.alerts_sent,
                        "llm_calls": result.llm_calls,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "estimated_cost_usd": round(result.estimated_cost_usd, 6),
                        "discarded": result.discarded,
                        "errors": len(result.errors),
                    },
                )
            return result
        finally:
            self.repository.release_run_lock()

    async def _process_candidate(self, candidate, profile_rows, result: PipelineResult) -> None:
        candidate = normalize_candidate(candidate)
        stored = self.repository.store_candidate(candidate)
        if stored.is_new_article:
            result.candidates_new += 1
        if candidate.source_type == "web_articles" and stored.is_new_article:
            result.web_articles_items_new += 1
        if not stored.is_new_article:
            if self.llm is not None and self.repository.event_needs_analysis(stored.event_id):
                await self._analyze(stored, candidate, profile_rows, result)
                return
            result.record_discard(DiscardReason.ALREADY_SEEN)
            return
        if not stored.is_new_event:
            if stored.should_reanalyze and self.llm is not None:
                await self._analyze(stored, candidate, profile_rows, result)
                return
            result.record_discard(DiscardReason.DUPLICATE)
            return

        reason = prefilter(
            candidate, self.enabled_profiles, self.lookback_hours, self.prefilter_min_score
        )
        if reason:
            self.repository.mark_discard(
                stored.candidate_record_id, stored.article_id, stored.event_id, reason
            )
            result.record_discard(reason)
            return

        if self.llm is None:
            result.prefilter_passed += 1
            if candidate.source_type == "web_articles":
                result.web_articles_prefilter_passed += 1
            return

        result.prefilter_passed += 1
        if candidate.source_type == "web_articles":
            result.web_articles_prefilter_passed += 1
        await self._analyze(stored, candidate, profile_rows, result)

    async def _analyze(self, stored, candidate, profile_rows, result: PipelineResult) -> None:
        assert self.llm is not None
        try:
            analysis = None
            for factual_attempt in range(2):
                result.llm_calls += 1
                try:
                    analysis = await self.llm.analyze_article(candidate, self.enabled_profiles)
                finally:
                    usage = self.llm.last_usage
                    result.input_tokens += usage.input_tokens
                    result.output_tokens += usage.output_tokens
                    result.estimated_cost_usd += usage.estimated_cost_usd
                try:
                    validate_factual_anchors(candidate, analysis)
                    break
                except StructuredOutputError:
                    if factual_attempt == 1:
                        raise
                    logger.warning(
                        "analysis_factual_anchor_retry",
                        extra={"exact_model_id": candidate.exact_model_id},
                    )
            assert analysis is not None
            waited = getattr(self.llm, "last_rate_limit_wait_seconds", 0.0)
            if waited:
                logger.info(
                    "event_llm_rate_limit_wait",
                    extra={
                        "run_id": str(result.run_id),
                        "event_id": str(stored.event_id),
                        "rate_limit_wait_seconds": round(waited, 3),
                        "llm_provider": type(self.llm).__name__,
                    },
                )
            expected = {profile.slug for profile in self.enabled_profiles}
            received = [evaluation.profile for evaluation in analysis.profiles]
            if len(received) != len(set(received)) or set(received) != expected:
                raise StructuredOutputError("LLM profile set does not match configured profiles")
        except (LLMRequestError, StructuredOutputError, ValueError) as error:
            self.repository.mark_analysis_failed(stored.candidate_record_id, stored.event_id)
            result.record_discard(DiscardReason.ANALYSIS_FAILED)
            result.errors.append(f"analysis: {type(error).__name__}")
            return

        scores = calculate_scores(analysis, candidate.source_trust, candidate.source_is_primary)
        self.repository.save_analysis(
            result.run_id,
            stored.event_id,
            stored.article_id,
            stored.evidence_upgrade_reason,
            analysis,
            profile_rows,
            scores,
        )
        result.analyzed += 1

        if analysis.hype_probability >= 0.9 and max(scores.values()) < self.alert_score_threshold:
            self.repository.mark_discard(
                stored.candidate_record_id,
                stored.article_id,
                stored.event_id,
                DiscardReason.HIGH_HYPE,
            )
            result.record_discard(DiscardReason.HIGH_HYPE)
        if (
            max(scores.values()) >= self.alert_score_threshold
            and analysis.confidence >= self.alert_confidence_threshold
            and self.alert_channel is not None
        ):
            await self._send_alert(stored.event_id, candidate, analysis, scores, result)

    async def _send_alert(self, event_id, candidate, analysis, scores, result) -> None:
        text = format_telegram_alert(candidate, analysis, scores, self.enabled_profiles)
        if getattr(self.alert_channel, "is_dry_run", False):
            await self.alert_channel.send(text)
            return
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        alert = self.repository.reserve_alert(event_id, fingerprint)
        if alert is None:
            return
        try:
            message_id = await self.alert_channel.send(text)
        except Exception as error:
            self.repository.mark_alert_failed(alert.id, type(error).__name__)
            result.errors.append(f"telegram: {type(error).__name__}")
            return
        self.repository.mark_alert_sent(alert.id, message_id)
        result.alerts_sent += 1

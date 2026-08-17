from __future__ import annotations

import hashlib
import logging
import re

from app.alerts.base import AlertChannel
from app.alerts.formatting import format_telegram_alert
from app.collectors.base import Collector
from app.db.repository import RadarRepository
from app.domain.models import DiscardReason, PipelineResult
from app.llm.base import LLMProvider
from app.llm.provider import LLMRequestError, StructuredOutputError
from app.pipeline.normalize import normalize_candidate
from app.pipeline.prefilter import is_outside_lookback, is_primary_bypass, prefilter
from app.pipeline.score import calculate_scores
from app.profiles.models import ProfileConfig

logger = logging.getLogger(__name__)

_CONCRETE_IDENTIFIER = re.compile(
    r"(?i)\b(?:deepseek(?:-ai/)?[-\w.]+|gpt[-\u2010-\u2015][\w.\u2010-\u2015+]+|"
    r"chatgpt\s+[a-z][\w-]+)\b"
)


def _normalize_anchor(value: str) -> str:
    value = value.casefold().strip().rsplit("/", 1)[-1]
    return re.sub(r"[^a-z0-9+]+", "-", value).strip("-")


def _concrete_identifiers(value: str) -> set[str]:
    return {_normalize_anchor(match.group()) for match in _CONCRETE_IDENTIFIER.finditer(value)}


def _analysis_text(analysis) -> str:
    values = [
        analysis.subject_name,
        analysis.what_happened,
        analysis.why_it_matters,
        analysis.what_changed or "",
    ]
    for evaluation in analysis.profiles:
        values.extend(
            [
                evaluation.reason,
                evaluation.suggested_action or "",
                " ".join(evaluation.related_topics),
            ]
        )
    return "\n".join(values)


def validate_factual_anchors(candidate, analysis) -> None:
    if candidate.exact_model_id:
        expected = _normalize_anchor(candidate.exact_model_id)
        returned = _normalize_anchor(analysis.subject_name)
        if returned != expected:
            raise StructuredOutputError(
                f"LLM subject_name {analysis.subject_name!r} contradicts exact_model_id "
                f"{candidate.exact_model_id!r}"
            )

    source_text = f"{getattr(candidate, 'title', '')}\n{getattr(candidate, 'summary', '')}"
    allowed = _concrete_identifiers(source_text)
    if candidate.exact_model_id:
        allowed.add(_normalize_anchor(candidate.exact_model_id))
        allowed.add(_normalize_anchor(candidate.exact_model_id.rsplit("/", 1)[-1]))
    returned_identifiers = _concrete_identifiers(_analysis_text(analysis))
    contradictions = returned_identifiers - allowed
    if allowed and contradictions:
        raise StructuredOutputError(
            f"LLM generated concrete identifiers absent from the source: {sorted(contradictions)}"
        )


def invalid_related_classes(analysis, profiles: list[ProfileConfig]) -> dict[str, list[int]]:
    allowed = {profile.slug: {item.class_id for item in profile.classes} for profile in profiles}
    return {
        evaluation.profile: [
            value
            for value in evaluation.related_classes
            if value not in allowed.get(evaluation.profile, set())
        ]
        for evaluation in analysis.profiles
        if any(
            value not in allowed.get(evaluation.profile, set())
            for value in evaluation.related_classes
        )
    }


def remove_invalid_related_classes(analysis, profiles: list[ProfileConfig]) -> None:
    allowed = {profile.slug: {item.class_id for item in profile.classes} for profile in profiles}
    for evaluation in analysis.profiles:
        evaluation.related_classes = [
            value
            for value in evaluation.related_classes
            if value in allowed.get(evaluation.profile, set())
        ]


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
        max_llm_calls_per_run: int = 50,
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
        self.max_llm_calls_per_run = max_llm_calls_per_run

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
                    if result.llm_call_limit_reached:
                        break
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
                        "prefilter_passed": result.prefilter_passed,
                        "primary_bypass_passed": result.primary_bypass_passed,
                        "pending_reanalysis": result.pending_reanalysis,
                        "evidence_reanalysis": result.evidence_reanalysis,
                        "analysis_retries": result.analysis_retries,
                        "llm_call_limit_reached": result.llm_call_limit_reached,
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
        if is_outside_lookback(candidate, self.lookback_hours):
            self.repository.mark_too_old(
                stored.candidate_record_id,
                stored.article_id,
                stored.event_id,
                new_event=stored.is_new_event,
            )
            result.record_discard(DiscardReason.TOO_OLD)
            return
        if not stored.is_new_article:
            if self.llm is not None and self.repository.event_needs_analysis(stored.event_id):
                result.pending_reanalysis += 1
                await self._analyze(stored, candidate, profile_rows, result)
                return
            result.record_discard(DiscardReason.ALREADY_SEEN)
            return
        if not stored.is_new_event:
            if stored.should_reanalyze and self.llm is not None:
                result.evidence_reanalysis += 1
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
        if is_primary_bypass(candidate, self.enabled_profiles, self.prefilter_min_score):
            result.primary_bypass_passed += 1
        if candidate.source_type == "web_articles":
            result.web_articles_prefilter_passed += 1
        await self._analyze(stored, candidate, profile_rows, result)

    async def _analyze(self, stored, candidate, profile_rows, result: PipelineResult) -> None:
        assert self.llm is not None
        try:
            analysis = None
            for structured_attempt in range(2):
                if result.llm_calls >= self.max_llm_calls_per_run:
                    result.llm_call_limit_reached = True
                    logger.warning(
                        "llm_call_limit_reached",
                        extra={"max_llm_calls_per_run": self.max_llm_calls_per_run},
                    )
                    return
                if structured_attempt:
                    result.analysis_retries += 1
                result.llm_calls += 1
                try:
                    analysis = await self.llm.analyze_article(
                        candidate, self.enabled_profiles, retry=structured_attempt > 0
                    )
                except StructuredOutputError:
                    if structured_attempt == 0:
                        logger.warning("analysis_structured_output_retry")
                        continue
                    raise
                finally:
                    usage = self.llm.last_usage
                    result.input_tokens += usage.input_tokens
                    result.output_tokens += usage.output_tokens
                    result.estimated_cost_usd += usage.estimated_cost_usd
                try:
                    validate_factual_anchors(candidate, analysis)
                    invalid_classes = invalid_related_classes(analysis, self.enabled_profiles)
                    if invalid_classes and structured_attempt == 0:
                        logger.warning(
                            "analysis_related_classes_retry",
                            extra={"invalid_related_classes": invalid_classes},
                        )
                        continue
                    if invalid_classes:
                        logger.warning(
                            "analysis_related_classes_removed",
                            extra={"invalid_related_classes": invalid_classes},
                        )
                        remove_invalid_related_classes(analysis, self.enabled_profiles)
                    break
                except StructuredOutputError:
                    log_extra = {
                        "exact_model_id": candidate.exact_model_id,
                        "returned_subject_name": analysis.subject_name,
                    }
                    if structured_attempt == 1:
                        logger.warning("analysis_factual_anchor_rejected", extra=log_extra)
                        raise
                    logger.warning("analysis_factual_anchor_retry", extra=log_extra)
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
            result.errors.append(f"analysis: {type(error).__name__}: {error}")
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

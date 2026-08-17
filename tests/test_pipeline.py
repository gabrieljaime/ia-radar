from datetime import UTC, datetime

import pytest
from conftest import RecordingChannel, StaticCollector, StaticLLM
from sqlalchemy import func, select

from app.alerts.dry_run import DryRunAlertChannel
from app.application.radar_service import RadarService
from app.db.models import Alert, Article, CandidateRecord, Event, EventScore
from app.domain.models import Candidate
from app.llm.base import LLMUsage
from app.llm.provider import LLMRequestError, StructuredOutputError


def candidate(
    title="Model X adds tool calling for AI agents",
    url="https://example.com/model-x",
    *,
    trust=100,
    primary=True,
    source_name="Official",
    requires_primary_verification=False,
    source_type="rss",
    exact_model_id=None,
):
    return Candidate(
        source_name=source_name,
        source_url=f"https://{source_name.lower().replace(' ', '-')}.example/feed",
        source_trust=trust,
        source_is_primary=primary,
        title=title,
        url=url,
        summary="Structured output, agent evaluation, tool calling and human oversight.",
        published_at=datetime.now(UTC),
        source_requires_primary_verification=requires_primary_verification,
        source_type=source_type,
        exact_model_id=exact_model_id,
    )


async def test_run_skips_cleanly_when_advisory_lock_is_busy(
    repository, profiles, analysis, monkeypatch
):
    collector = StaticCollector([candidate()])
    llm = StaticLLM(analysis)
    monkeypatch.setattr(repository, "try_acquire_run_lock", lambda: False)
    result = await RadarService(collector, llm, repository, profiles, RecordingChannel()).run()
    assert result.skipped is True
    assert result.run_id is None
    assert llm.calls == 0


async def test_advisory_lock_is_released_when_collection_fails(repository, profiles, monkeypatch):
    released = False

    class FailingCollector:
        errors = []

        async def collect(self):
            raise RuntimeError("collector failed")

    def release():
        nonlocal released
        released = True

    monkeypatch.setattr(repository, "release_run_lock", release)
    with pytest.raises(RuntimeError, match="collector failed"):
        await RadarService(FailingCollector(), None, repository, profiles, RecordingChannel()).run()
    assert released is True


async def test_pipeline_is_idempotent_and_sends_one_alert(repository, session, profiles, analysis):
    llm = StaticLLM(analysis)
    channel = RecordingChannel()
    service = RadarService(StaticCollector([candidate()]), llm, repository, profiles, channel)
    first = await service.run()
    second = await service.run()
    assert first.analyzed == 1
    assert second.analyzed == 0
    assert second.discarded == {"already_seen": 1}
    assert llm.calls == 1
    assert len(channel.messages) == 1
    assert session.scalar(select(func.count()).select_from(Event)) == 1
    assert session.scalar(select(func.count()).select_from(Article)) == 1
    assert session.scalar(select(func.count()).select_from(EventScore)) == 4
    assert session.scalar(select(func.count()).select_from(Alert)) == 1
    records = session.scalars(select(CandidateRecord)).all()
    assert [record.discard_reason for record in records] == [None, "already_seen"]


async def test_similar_articles_become_one_event(repository, session, profiles, analysis):
    first = candidate()
    second = candidate("Model X adds tool-calling for AI agents", "https://other.example/model-x")
    service = RadarService(
        StaticCollector([first, second]),
        StaticLLM(analysis),
        repository,
        profiles,
        RecordingChannel(),
    )
    result = await service.run()
    assert result.analyzed == 1
    assert result.discarded == {"duplicate": 1}
    assert session.scalar(select(func.count()).select_from(Event)) == 1
    assert session.scalar(select(func.count()).select_from(Article)) == 2
    assert (
        session.scalar(
            select(CandidateRecord.discard_reason).where(
                CandidateRecord.discard_reason == "duplicate"
            )
        )
        == "duplicate"
    )


async def test_model_artifact_and_expert_article_become_one_event(
    repository, session, profiles, analysis
):
    base = candidate("Qwen3.8-27B", "https://qwen.example/qwen38")
    artifact = candidate(
        "New model repository: Qwen/Qwen3.8-27B-FP8",
        "https://huggingface.co/Qwen/Qwen3.8-27B-FP8",
        source_name="Qwen HF",
        source_type="huggingface_models",
        exact_model_id="Qwen/Qwen3.8-27B-FP8",
    )
    expert = candidate(
        "Qwen 3.8 27B is excellent",
        "https://simonwillison.net/qwen-38",
        source_name="Simon Willison",
        primary=False,
    )
    result = await RadarService(
        StaticCollector([base, artifact, expert]), StaticLLM(analysis), repository, profiles, None
    ).run()
    assert result.analyzed == 1
    assert session.scalar(select(func.count()).select_from(Event)) == 1
    assert session.scalar(select(func.count()).select_from(Article)) == 3


async def test_same_content_with_different_titles_is_exact_duplicate(
    repository, session, profiles, analysis
):
    first = candidate("Model X arrives", "https://example.com/model-x")
    second = candidate("Official announcement", "https://other.example/announcement")
    second.summary = first.summary
    service = RadarService(
        StaticCollector([first, second]),
        StaticLLM(analysis),
        repository,
        profiles,
        RecordingChannel(),
        prefilter_min_score=0,
    )
    result = await service.run()
    assert result.analyzed == 1
    assert result.discarded == {"duplicate": 1}
    assert session.scalar(select(func.count()).select_from(Event)) == 1


async def test_distinct_titles_above_fuzzy_threshold_share_event(
    repository, session, profiles, analysis
):
    first = candidate("Model X adds tool calling for AI agents")
    second = candidate(
        "Model X adds tool calling to AI agents", "https://different.example/model-x"
    )
    service = RadarService(
        StaticCollector([first, second]),
        StaticLLM(analysis),
        repository,
        profiles,
        RecordingChannel(),
    )
    await service.run()
    assert session.scalar(select(func.count()).select_from(Event)) == 1
    assert session.scalar(select(func.count()).select_from(Article)) == 2


async def test_telegram_failure_preserves_failed_alert(repository, session, profiles, analysis):
    service = RadarService(
        StaticCollector([candidate()]),
        StaticLLM(analysis),
        repository,
        profiles,
        RecordingChannel(RuntimeError("unavailable")),
    )
    result = await service.run()
    alert = session.scalar(select(Alert))
    assert result.alerts_sent == 0
    assert alert.delivery_status == "failed"
    assert alert.error_code == "RuntimeError"


class InvalidLLM:
    last_usage = LLMUsage()

    async def analyze_article(self, candidate, profiles):
        raise StructuredOutputError("bad payload")


async def test_invalid_structured_output_does_not_break_run(repository, session, profiles):
    service = RadarService(
        StaticCollector([candidate(), candidate(url="https://example.com/another")]),
        InvalidLLM(),
        repository,
        profiles,
        RecordingChannel(),
    )
    result = await service.run()
    assert result.discarded["analysis_failed"] >= 1
    assert result.errors
    assert session.scalar(select(func.count()).select_from(Event)) >= 1


async def test_dry_run_does_not_reserve_telegram_alert(
    repository, session, profiles, analysis, capsys
):
    service = RadarService(
        StaticCollector([candidate()]),
        StaticLLM(analysis),
        repository,
        profiles,
        DryRunAlertChannel(),
    )
    await service.run()
    assert "WOULD_ALERT" in capsys.readouterr().out
    assert session.scalar(select(func.count()).select_from(Alert)) == 0


async def test_dry_run_without_llm_leaves_event_pending(repository, session, profiles):
    service = RadarService(
        StaticCollector([candidate()]), None, repository, profiles, DryRunAlertChannel()
    )
    result = await service.run()
    event = session.scalar(select(Event))
    assert result.analyzed == 0
    assert result.llm_calls == 0
    assert event.status == "pending"


async def test_pending_event_can_be_analyzed_on_later_run(repository, session, profiles, analysis):
    item = candidate()
    await RadarService(
        StaticCollector([item]), None, repository, profiles, DryRunAlertChannel()
    ).run()
    result = await RadarService(
        StaticCollector([candidate()]),
        StaticLLM(analysis),
        repository,
        profiles,
        DryRunAlertChannel(),
    ).run()
    event = session.scalar(select(Event))
    assert result.analyzed == 1
    assert event.status == "analyzed"


async def test_four_profiles_use_one_llm_request(repository, profiles, analysis):
    llm = StaticLLM(analysis)
    result = await RadarService(
        StaticCollector([candidate()]), llm, repository, profiles, RecordingChannel()
    ).run()
    assert len(profiles) == 4
    assert llm.calls == result.llm_calls == 1
    assert set(llm.profile_calls[0]) == {profile.slug for profile in profiles}


async def test_disabled_profile_is_not_sent_or_scored(repository, session, profiles, analysis):
    configured = [
        profile.model_copy(update={"enabled": False}) if profile.slug == "bank_risk" else profile
        for profile in profiles
    ]
    analysis.profiles = [item for item in analysis.profiles if item.profile != "bank_risk"]
    llm = StaticLLM(analysis)
    result = await RadarService(
        StaticCollector([candidate()]), llm, repository, configured, RecordingChannel()
    ).run()
    assert result.analyzed == 1
    assert llm.calls == 1
    assert "bank_risk" not in llm.profile_calls[0]
    assert len(llm.profile_calls[0]) == 3
    assert session.scalar(select(func.count()).select_from(EventScore)) == 3


async def test_single_enabled_profile_still_uses_one_request(repository, profiles, analysis):
    configured = [
        profile.model_copy(update={"enabled": profile.slug == "general_ai"}) for profile in profiles
    ]
    analysis.profiles = [item for item in analysis.profiles if item.profile == "general_ai"]
    llm = StaticLLM(analysis)
    result = await RadarService(
        StaticCollector([candidate()]), llm, repository, configured, RecordingChannel()
    ).run()
    assert result.analyzed == 1
    assert llm.calls == result.llm_calls == 1
    assert llm.profile_calls == [["general_ai"]]


@pytest.mark.parametrize("invalid_case", ["missing", "unknown", "duplicate", "disabled"])
async def test_profile_ids_must_exactly_match_enabled_configuration(
    repository, profiles, analysis, invalid_case
):
    configured = profiles
    if invalid_case == "missing":
        analysis.profiles = analysis.profiles[:-1]
    elif invalid_case == "unknown":
        analysis.profiles[-1].profile = "marketing"
    elif invalid_case == "duplicate":
        analysis.profiles.append(analysis.profiles[0].model_copy(deep=True))
    else:
        configured = [
            profile.model_copy(update={"enabled": False})
            if profile.slug == "bank_risk"
            else profile
            for profile in profiles
        ]
    result = await RadarService(
        StaticCollector([candidate()]),
        StaticLLM(analysis),
        repository,
        configured,
        RecordingChannel(),
    ).run()
    assert result.discarded == {"analysis_failed": 1}


class RateLimitedLLM:
    last_usage = LLMUsage()

    async def analyze_article(self, candidate, profiles):
        raise LLMRequestError("retries exhausted")


async def test_exhausted_429_marks_event_failed_without_aborting_run(repository, profiles):
    result = await RadarService(
        StaticCollector([candidate()]), RateLimitedLLM(), repository, profiles, RecordingChannel()
    ).run()
    assert result.discarded == {"analysis_failed": 1}
    assert result.errors == ["analysis: LLMRequestError"]


async def test_high_relevance_below_alert_threshold_does_not_alert(repository, profiles, analysis):
    for evaluation in analysis.profiles:
        evaluation.relevance_score = 100
        evaluation.alert_score = 85
    analysis.confidence = 0.95
    analysis.hype_probability = 0
    channel = RecordingChannel()
    await RadarService(
        StaticCollector([candidate()]), StaticLLM(analysis), repository, profiles, channel
    ).run()
    assert channel.messages == []


async def test_alert_score_above_threshold_can_alert(repository, profiles, analysis):
    for evaluation in analysis.profiles:
        evaluation.relevance_score = 80
        evaluation.alert_score = 94
    analysis.confidence = 0.95
    analysis.hype_probability = 0
    channel = RecordingChannel()
    await RadarService(
        StaticCollector([candidate()]), StaticLLM(analysis), repository, profiles, channel
    ).run()
    assert len(channel.messages) == 1


async def test_secondary_to_primary_upgrades_evidence_and_reanalyzes_once(
    repository, session, profiles, analysis
):
    llm = StaticLLM(analysis)
    secondary = candidate(
        url="https://secondary.example/model-x",
        trust=85,
        primary=False,
        source_name="Secondary",
        requires_primary_verification=True,
    )
    await RadarService(
        StaticCollector([secondary]), llm, repository, profiles, RecordingChannel()
    ).run()
    official = candidate(
        url="https://official.example/model-x", source_name="Official", trust=100, primary=True
    )
    result = await RadarService(
        StaticCollector([official]), llm, repository, profiles, RecordingChannel()
    ).run()
    event = session.scalar(select(Event))
    assert result.analyzed == 1
    assert llm.calls == 2
    assert event.analysis_count == 2
    assert event.primary_source_verified is True
    assert event.primary_source_url == "https://official.example/model-x"
    assert event.evidence_upgrade_reason == "primary_source_discovered"
    assert event.origin_article_id != event.analysis_article_id


async def test_equal_trust_duplicate_does_not_reanalyze(repository, session, profiles, analysis):
    llm = StaticLLM(analysis)
    first = candidate(url="https://one.example/model-x", trust=85, primary=False, source_name="One")
    second = candidate(
        url="https://two.example/model-x", trust=85, primary=False, source_name="Two"
    )
    await RadarService(
        StaticCollector([first]), llm, repository, profiles, RecordingChannel()
    ).run()
    result = await RadarService(
        StaticCollector([second]), llm, repository, profiles, RecordingChannel()
    ).run()
    assert llm.calls == 1
    assert result.discarded == {"duplicate": 1}
    assert session.scalar(select(Event)).analysis_count == 1


async def test_mirror_alone_is_not_primary_verified(repository, session, profiles, analysis):
    mirror = candidate(
        trust=65,
        primary=False,
        source_name="Mirror",
        requires_primary_verification=True,
    )
    await RadarService(
        StaticCollector([mirror]),
        StaticLLM(analysis),
        repository,
        profiles,
        RecordingChannel(),
    ).run()
    event = session.scalar(select(Event))
    assert event.primary_source_verified is False
    assert event.primary_source_url is None


async def test_failed_event_can_retry_once_with_primary_evidence(
    repository, session, profiles, analysis
):
    secondary = candidate(
        url="https://secondary.example/model-x",
        trust=85,
        primary=False,
        source_name="Secondary",
    )
    await RadarService(
        StaticCollector([secondary]), InvalidLLM(), repository, profiles, RecordingChannel()
    ).run()
    llm = StaticLLM(analysis)
    official = candidate(
        url="https://official.example/model-x", trust=100, primary=True, source_name="Official"
    )
    result = await RadarService(
        StaticCollector([official]), llm, repository, profiles, RecordingChannel()
    ).run()
    event = session.scalar(select(Event))
    assert result.analyzed == 1
    assert llm.calls == 1
    assert event.status == "analyzed"
    assert event.analysis_count == 1

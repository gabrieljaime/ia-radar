import pytest
from pydantic import ValidationError

from app.llm.schemas import ArticleAnalysis


def test_loads_four_complete_profiles(profiles):
    assert {profile.slug for profile in profiles} == {
        "educator",
        "ai_agent_developer",
        "bank_risk",
        "general_ai",
    }
    assert all(profile.topics for profile in profiles)
    assert all(profile.enabled and profile.icon for profile in profiles)


def test_structured_output_rejects_out_of_range_score(analysis):
    payload = analysis.model_dump()
    payload["profiles"][0]["actionability_score"] = 101
    with pytest.raises(ValidationError):
        ArticleAnalysis.model_validate(payload)


def test_all_profile_dimensions_accept_independent_scores(analysis):
    evaluation = analysis.profiles[0]
    evaluation.relevance_score = 95
    evaluation.alert_score = 70
    assert evaluation.relevance_score == 95
    assert evaluation.alert_score == 70
    assert all(
        0 <= value <= 100
        for value in (
            evaluation.relevance_score,
            evaluation.novelty_score,
            evaluation.actionability_score,
            evaluation.strategic_impact_score,
            evaluation.alert_score,
        )
    )


def test_general_ai_profile_is_calibrated_for_significance_not_corporate_noise(profiles):
    general = next(profile for profile in profiles if profile.slug == "general_ai")
    assert "nuevas generaciones" in general.description
    assert "ruido corporativo" in general.description

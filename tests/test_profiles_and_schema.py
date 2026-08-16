import pytest
from pydantic import ValidationError

from app.llm.schemas import ArticleAnalysis


def test_loads_three_complete_profiles(profiles):
    assert {profile.slug for profile in profiles} == {"educator", "course", "bank"}
    assert all(profile.topics for profile in profiles)


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

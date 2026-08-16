import pytest
from pydantic import ValidationError

from app.llm.schemas import ArticleAnalysis


def test_loads_three_complete_profiles(profiles):
    assert {profile.slug for profile in profiles} == {"educator", "course", "bank"}
    assert all(profile.topics for profile in profiles)


def test_structured_output_rejects_out_of_range_score(analysis):
    payload = analysis.model_dump()
    payload["novelty_score"] = 101
    with pytest.raises(ValidationError):
        ArticleAnalysis.model_validate(payload)

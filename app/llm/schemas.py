import re

from pydantic import BaseModel, Field, field_validator

_PERCENT_ENCODED_BYTE = re.compile(r"%[0-9a-fA-F]{2}")


def _require_unicode_text(value: str | None) -> str | None:
    if value is not None and _PERCENT_ENCODED_BYTE.search(value):
        raise ValueError(
            "generated text must contain Unicode characters, not percent-encoded bytes"
        )
    return value


class ProfileEvaluation(BaseModel):
    profile: str
    relevance_score: int = Field(ge=0, le=100)
    novelty_score: int = Field(ge=0, le=100)
    actionability_score: int = Field(ge=0, le=100)
    strategic_impact_score: int = Field(ge=0, le=100)
    alert_score: int = Field(ge=0, le=100)
    reason: str
    suggested_action: str | None = None
    related_topics: list[str]
    related_classes: list[int] = Field(default_factory=list)

    _validate_reason = field_validator("reason")(_require_unicode_text)
    _validate_action = field_validator("suggested_action")(_require_unicode_text)


class ArticleAnalysis(BaseModel):
    subject_name: str
    subject_type: str
    summary: str
    what_happened: str
    why_it_matters: str
    what_changed: str | None = None
    novelty_score: int = Field(ge=0, le=100)
    credibility_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    hype_probability: float = Field(ge=0, le=1)
    profiles: list[ProfileEvaluation]

    _validate_generated_text = field_validator(
        "subject_name", "subject_type", "summary", "what_happened", "why_it_matters", "what_changed"
    )(_require_unicode_text)

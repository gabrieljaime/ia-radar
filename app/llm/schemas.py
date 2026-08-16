from pydantic import BaseModel, Field


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


class ArticleAnalysis(BaseModel):
    summary: str
    what_happened: str
    why_it_matters: str
    what_changed: str | None = None
    novelty_score: int = Field(ge=0, le=100)
    credibility_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    hype_probability: float = Field(ge=0, le=1)
    profiles: list[ProfileEvaluation]

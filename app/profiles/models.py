from pydantic import BaseModel, Field


class ProfileActions(BaseModel):
    suggest_teaching_use: bool = False
    suggest_research_use: bool = False
    identify_related_class: bool = False
    suggest_demo: bool = False
    suggest_course_update: bool = False
    suggest_internal_use_case: bool = False
    highlight_regulatory_impact: bool = False


class ProfileConfig(BaseModel):
    slug: str
    name: str
    description: str
    topics: dict[str, float]
    entities: dict[str, float] = Field(default_factory=dict)
    actions: ProfileActions = Field(default_factory=ProfileActions)
    enabled: bool = True


class ProfilesConfig(BaseModel):
    profiles: list[ProfileConfig]

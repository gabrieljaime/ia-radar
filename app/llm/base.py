from dataclasses import dataclass
from typing import Protocol

from app.domain.models import Candidate
from app.llm.schemas import ArticleAnalysis
from app.profiles.models import ProfileConfig


@dataclass(slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class LLMProvider(Protocol):
    last_usage: LLMUsage

    async def analyze_article(
        self, candidate: Candidate, profiles: list[ProfileConfig], *, retry: bool = False
    ) -> ArticleAnalysis: ...

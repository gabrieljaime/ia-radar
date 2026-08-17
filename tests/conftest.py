import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.repository import RadarRepository
from app.llm.base import LLMUsage
from app.llm.schemas import ArticleAnalysis
from app.profiles.loader import load_profiles


class StaticLLM:
    def __init__(self, analysis: ArticleAnalysis):
        self.analysis = analysis
        self.calls = 0
        self.profile_calls = []
        self.last_usage = LLMUsage()

    async def analyze_article(self, candidate, profiles):
        self.calls += 1
        self.profile_calls.append([profile.slug for profile in profiles])
        return self.analysis


class StaticCollector:
    def __init__(self, candidates):
        self.candidates = candidates
        self.errors = []

    async def collect(self):
        return self.candidates


class RecordingChannel:
    def __init__(self, failure: Exception | None = None):
        self.messages = []
        self.failure = failure

    async def send(self, text):
        self.messages.append(text)
        if self.failure:
            raise self.failure
        return str(len(self.messages))


@pytest.fixture
def analysis() -> ArticleAnalysis:
    data = json.loads(Path("tests/fixtures/analysis.json").read_text(encoding="utf-8"))
    return ArticleAnalysis.model_validate(data)


@pytest.fixture
def profiles():
    return load_profiles(Path("config/profiles"))


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        yield value


@pytest.fixture
def repository(session):
    return RadarRepository(session)

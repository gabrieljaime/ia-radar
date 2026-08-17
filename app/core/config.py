from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class RSSSourceConfig(BaseModel):
    name: str
    url: HttpUrl
    category: str
    trust_level: int = Field(ge=0, le=100)
    is_primary: bool = True
    enabled: bool = True
    requires_primary_verification: bool = False


class WebChangelogSourceConfig(RSSSourceConfig):
    parser: str


class WebArticlesSourceConfig(RSSSourceConfig):
    parser: str


class GitHubReleasesSourceConfig(RSSSourceConfig):
    repo: str


class HuggingFaceModelsSourceConfig(RSSSourceConfig):
    organization: str
    limit: int = Field(default=20, ge=1, le=100)


class SourcesConfig(BaseModel):
    rss: list[RSSSourceConfig]
    web_changelog: list[WebChangelogSourceConfig] = Field(default_factory=list)
    web_articles: list[WebArticlesSourceConfig] = Field(default_factory=list)
    github_releases: list[GitHubReleasesSourceConfig] = Field(default_factory=list)
    huggingface_models: list[HuggingFaceModelsSourceConfig] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ai_radar:ai_radar@localhost:5432/ai_radar"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-nano"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_input_cost_per_million_usd: float = 0.0
    llm_output_cost_per_million_usd: float = 0.0
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    log_level: str = "INFO"
    config_dir: Path = Path("config")
    request_timeout_seconds: float = 20.0
    radar_lookback_hours: int = Field(default=48, gt=0)
    llm_max_requests_per_minute: int = Field(default=8, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    radar_max_llm_calls_per_run: int = Field(default=50, gt=0)
    output_language: str = "es"
    digest_lookback_hours: int = Field(default=24, gt=0)
    digest_max_items: int = Field(default=10, gt=0)
    digest_min_alert_score: int = Field(default=60, ge=0, le=100)
    digest_max_actions: int = Field(default=3, ge=0)
    prefilter_min_score: int = 20
    dedupe_title_threshold: float = 88.0
    alert_score_threshold: int = 90
    alert_confidence_threshold: float = 0.75


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_sources(path: Path) -> SourcesConfig:
    with path.open(encoding="utf-8") as file:
        return SourcesConfig.model_validate(yaml.safe_load(file))

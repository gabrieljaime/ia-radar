from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from app.core.config import HuggingFaceModelsSourceConfig
from app.domain.models import Candidate


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class HuggingFaceModelsCollector:
    def __init__(self, sources, client: httpx.AsyncClient, max_concurrency: int = 3):
        self.sources = [source for source in sources if source.enabled]
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.errors: list[str] = []
        self.health: list[dict] = []

    async def collect(self) -> list[Candidate]:
        groups = await asyncio.gather(*(self._collect_source(source) for source in self.sources))
        return [candidate for group in groups for candidate in group]

    async def _collect_source(self, source: HuggingFaceModelsSourceConfig) -> list[Candidate]:
        status = None
        try:
            async with self.semaphore:
                response = await self.client.get(
                    "https://huggingface.co/api/models",
                    params={
                        "author": source.organization,
                        "sort": "createdAt",
                        "direction": -1,
                        "limit": source.limit,
                        "full": "false",
                    },
                )
            status = response.status_code
            response.raise_for_status()
            models = response.json()
            if not isinstance(models, list):
                raise ValueError("Hugging Face response is not a list")
            models = [model for model in models if model.get("id") and model.get("createdAt")]
            if not models:
                self._health(source.name, status, [], "EMPTY")
                return []
            self._health(source.name, status, models, "OK")
            return [self._candidate(source, model) for model in models]
        except httpx.HTTPError as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self._health(source.name, status, [], "API_ERROR")
            return []
        except (TypeError, ValueError) as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self._health(source.name, status, [], "PARSE_ERROR")
            return []

    @staticmethod
    def _candidate(source, model) -> Candidate:
        model_id = model["id"]
        tags = ", ".join(model.get("tags", [])[:12])
        return Candidate(
            source_name=source.name,
            source_url=str(source.url),
            source_trust=source.trust_level,
            source_is_primary=source.is_primary,
            title=f"New model repository: {model_id}",
            url=f"https://huggingface.co/{model_id}",
            summary=f"Official model publication. Model family/tags: {tags}",
            published_at=_datetime(model["createdAt"]),
            source_type="huggingface_models",
            source_requires_primary_verification=source.requires_primary_verification,
            external_id=model_id,
        )

    def _health(self, name, status, models, state):
        latest = max((_datetime(item.get("createdAt")) for item in models), default=None)
        self.health.append(
            {
                "source": name,
                "http_status": status,
                "items": len(models),
                "latest": latest,
                "status": state,
            }
        )

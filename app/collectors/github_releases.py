from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from app.core.config import GitHubReleasesSourceConfig
from app.domain.models import Candidate


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class GitHubReleasesCollector:
    def __init__(self, sources, client: httpx.AsyncClient, max_concurrency: int = 3):
        self.sources = [source for source in sources if source.enabled]
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.errors: list[str] = []
        self.health: list[dict] = []

    async def collect(self) -> list[Candidate]:
        groups = await asyncio.gather(*(self._collect_source(source) for source in self.sources))
        return [candidate for group in groups for candidate in group]

    async def _collect_source(self, source: GitHubReleasesSourceConfig) -> list[Candidate]:
        status = None
        try:
            async with self.semaphore:
                response = await self.client.get(
                    f"https://api.github.com/repos/{source.repo}/releases",
                    params={"per_page": 20},
                    headers={"Accept": "application/vnd.github+json"},
                )
            status = response.status_code
            response.raise_for_status()
            releases = response.json()
            if not isinstance(releases, list):
                raise ValueError("GitHub Releases response is not a list")
            releases = [release for release in releases if not release.get("draft")]
            if not releases:
                self._health(source.name, status, [], "EMPTY")
                return []
            self._health(source.name, status, releases, "OK")
            return [self._candidate(source, release) for release in releases]
        except httpx.HTTPError as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self._health(source.name, status, [], "API_ERROR")
            return []
        except (KeyError, TypeError, ValueError) as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self._health(source.name, status, [], "PARSE_ERROR")
            return []

    @staticmethod
    def _candidate(source, release) -> Candidate:
        title = release.get("name") or release["tag_name"]
        prerelease = bool(release.get("prerelease"))
        summary = release.get("body") or ""
        if prerelease:
            summary = f"Prerelease (lower priority). {summary}"
        return Candidate(
            source_name=source.name,
            source_url=str(source.url),
            source_trust=source.trust_level,
            source_is_primary=source.is_primary,
            title=title,
            url=release["html_url"],
            summary=summary,
            published_at=_datetime(release.get("published_at")),
            source_type="github_releases",
            source_requires_primary_verification=source.requires_primary_verification,
            external_id=str(release["id"]),
        )

    def _health(self, name, status, releases, state):
        latest = max((_datetime(item.get("published_at")) for item in releases), default=None)
        self.health.append(
            {
                "source": name,
                "http_status": status,
                "items": len(releases),
                "latest": latest,
                "status": state,
            }
        )

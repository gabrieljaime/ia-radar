from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.collectors.github_releases import GitHubReleasesCollector
from app.collectors.huggingface_models import HuggingFaceModelsCollector
from app.collectors.web_articles import parse_kimi
from app.collectors.web_changelog import parse_cohere, parse_deepseek, parse_openai_api
from app.core.config import GitHubReleasesSourceConfig, HuggingFaceModelsSourceConfig

FIXTURES = Path("tests/fixtures")


def test_new_changelog_parsers_use_common_shape():
    html = (FIXTURES / "source_expansion_changelogs.html").read_text(encoding="utf-8")
    for parser in (parse_openai_api, parse_deepseek, parse_cohere):
        items = parser(html, "https://example.com/changelog")
        assert len(items) == 1
        assert items[0]["title"]
        assert items[0]["url"].startswith("https://")
        assert items[0]["published_at"] is not None


def test_kimi_parser_preserves_non_english_title():
    html = (FIXTURES / "kimi_blog.html").read_text(encoding="utf-8")
    items = parse_kimi(html, "https://platform.kimi.com/blog")
    assert items[0].title == "Kimi K2 推理模型"
    assert items[0].published_at == datetime(2026, 8, 13, tzinfo=UTC)


def github_source(repo="owner/repo"):
    return GitHubReleasesSourceConfig(
        name="Releases",
        url=f"https://github.com/{repo}/releases",
        repo=repo,
        category="github_releases",
        trust_level=95,
        is_primary=True,
    )


async def test_github_releases_ignores_drafts_and_marks_prereleases():
    payload = [
        {
            "id": 1,
            "name": "v2.0",
            "tag_name": "v2.0",
            "html_url": "https://x/v2",
            "published_at": "2026-08-13T00:00:00Z",
            "body": "breaking change",
            "draft": False,
            "prerelease": True,
        },
        {
            "id": 2,
            "tag_name": "draft",
            "html_url": "https://x/draft",
            "published_at": "2026-08-13T00:00:00Z",
            "body": "",
            "draft": True,
        },
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        candidates = await GitHubReleasesCollector([github_source()], client).collect()
    assert len(candidates) == 1
    assert candidates[0].source_type == "github_releases"
    assert candidates[0].summary.startswith("Prerelease (lower priority).")


def hf_source():
    return HuggingFaceModelsSourceConfig(
        name="Qwen HF",
        url="https://huggingface.co/Qwen",
        organization="Qwen",
        category="huggingface_models",
        trust_level=95,
        is_primary=True,
    )


async def test_huggingface_identity_uses_model_id_not_repo_updates():
    payload = [
        {
            "id": "Qwen/Qwen4",
            "createdAt": "2026-08-13T00:00:00Z",
            "lastModified": "2026-08-16T00:00:00Z",
            "tags": ["text-generation"],
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        first = await HuggingFaceModelsCollector([hf_source()], client).collect()
        payload[0]["lastModified"] = "2026-08-17T00:00:00Z"
        second = await HuggingFaceModelsCollector([hf_source()], client).collect()
    assert first[0].external_id == second[0].external_id == "Qwen/Qwen4"
    assert first[0].url == second[0].url
    assert first[0].published_at == second[0].published_at


async def test_api_collectors_fail_safe():
    async def handler(request):
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        github = GitHubReleasesCollector([github_source()], client)
        huggingface = HuggingFaceModelsCollector([hf_source()], client)
        assert await github.collect() == []
        assert await huggingface.collect() == []
    assert github.health[0]["status"] == "API_ERROR"
    assert huggingface.health[0]["status"] == "API_ERROR"

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.application.radar_service import validate_factual_anchors
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


def test_cohere_entries_are_parsed_atomically_without_neighbor_contamination():
    html = """
    <script>var frontmatter = {"title": "Command A Vision", "slug":
    "changelog/command-a-vision", "createdAt": "Mon Aug 10 2026 09:00:00 (EST)",
    "description": "Command A Vision processes images."};</script>
    <script>var frontmatter = {"title": "Command A", "slug": "changelog/command-a",
    "createdAt": "Mon Aug 11 2026 09:00:00 (EST)", "description":
    "Command A is the flagship model."};</script>
    """
    vision, command = parse_cohere(html, "https://docs.cohere.com/v2/changelog")
    assert "Vision" in vision["summary"]
    assert "Reasoning" not in vision["summary"]
    assert "Command A is" in command["summary"]
    assert "Command R 7B" not in command["summary"]


def test_factual_anchor_rejects_related_but_different_model(analysis):
    candidate = type("Anchored", (), {"exact_model_id": "Qwen/Qwen3.8-2.4T-A95B"})()
    wrong = analysis.model_copy(update={"subject_name": "Qwen/Qwen3.8-27B"})
    with pytest.raises(ValueError, match="contradicts"):
        validate_factual_anchors(candidate, wrong)


@pytest.mark.parametrize(
    ("expected", "wrong"),
    [
        ("Cohere/Command-A-Vision", "Cohere/Command-A-Reasoning"),
        ("Cohere/Command-A", "Cohere/Command-R-7B"),
        ("zai-org/GLM-5.2", "zai-org/GLM-5.2-FP8"),
    ],
)
def test_factual_anchor_rejects_identifier_substitution(analysis, expected, wrong):
    candidate = type("Anchored", (), {"exact_model_id": expected})()
    with pytest.raises(ValueError, match="contradicts"):
        validate_factual_anchors(candidate, analysis.model_copy(update={"subject_name": wrong}))

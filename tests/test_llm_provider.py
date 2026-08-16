from pathlib import Path

import httpx
import pytest

from app.domain.models import Candidate
from app.llm.provider import OpenAICompatibleLLMProvider, StructuredOutputError


async def test_invalid_provider_structured_output_is_rejected(profiles):
    async def handler(request):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"novelty_score": 101}'}}]},
        )

    provider = OpenAICompatibleLLMProvider("test-key", "test-model", "https://llm.example")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="https://llm.example", transport=httpx.MockTransport(handler)
    )
    candidate = Candidate(
        "Official", "https://feed.example", 100, True, "AI model", "https://example/a", "", None
    )
    with pytest.raises(StructuredOutputError):
        await provider.analyze_article(candidate, profiles)
    await provider.close()


async def test_provider_records_reported_token_usage(profiles):
    analysis = Path("tests/fixtures/analysis.json").read_text(encoding="utf-8")

    async def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": analysis}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    provider = OpenAICompatibleLLMProvider(
        "test-key",
        "test-model",
        "https://llm.example",
        input_cost_per_million_usd=1,
        output_cost_per_million_usd=2,
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="https://llm.example", transport=httpx.MockTransport(handler)
    )
    candidate = Candidate(
        "Official", "https://feed.example", 100, True, "AI model", "https://example/a", "", None
    )
    result = await provider.analyze_article(candidate, profiles)
    assert result.novelty_score == 96
    assert provider.last_usage.input_tokens == 1000
    assert provider.last_usage.output_tokens == 500
    assert provider.last_usage.estimated_cost_usd == pytest.approx(0.002)
    await provider.close()

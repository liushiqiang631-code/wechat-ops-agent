from __future__ import annotations

import pytest

from app.domain.models import ResearchPack, WebSearchHit, WebSearchResult
from app.services.models.deepseek import ModelResult, ModelUsage
from app.skills.research import ResearchSkill


class RecordingModel:
    def __init__(self, pack: ResearchPack):
        self.pack = pack
        self.user_payload: str | None = None

    async def generate_structured(self, *, system, user, response_model, **_: object):
        self.user_payload = user
        return ModelResult(data=self.pack, usage=ModelUsage(), model="fake")


class FakeSearch:
    def __init__(self, hits: list[WebSearchHit]):
        self.hits = hits
        self.queries: list[str] = []

    async def search(self, query: str, limit: int | None = None) -> WebSearchResult:
        self.queries.append(query)
        return WebSearchResult(query=query, hits=self.hits, provider="jina_bing")


@pytest.mark.asyncio
async def test_research_skill_uses_web_search_to_extend_sources():
    pack = ResearchPack(
        topic="deepseek harness",
        claims=[
            {
                "claim": "DeepSeek Harness 一切皆插件",
                "source_url": "https://github.com/deepseek-ai/deepseek-harness",
                "source_title": "DeepSeek Harness",
                "publisher": "DeepSeek",
                "retrieved_at": "2026-08-16T00:00:00+08:00",
                "source_type": "official_repo",
                "confidence": 0.9,
            }
        ],
        sources=["https://github.com/deepseek-ai/deepseek-harness"],
    )
    model = RecordingModel(pack)
    search = FakeSearch(
        hits=[
            WebSearchHit(
                url="https://www.deepseek.com/harness/en/",
                title="DeepSeek Harness developer preview",
                snippet="Everything is a plugin.",
            )
        ]
    )
    skill = ResearchSkill(model, fetcher=None, search=None)

    result = await skill.run(
        "deepseek harness",
        ["https://github.com/deepseek-ai/deepseek-harness"],
        search=search,
    )

    assert search.queries == ["deepseek harness"]
    assert result.search_hits == search.hits
    assert "https://www.deepseek.com/harness/en/" in model.user_payload
    assert "DeepSeek Harness developer preview" in model.user_payload


@pytest.mark.asyncio
async def test_research_skill_without_search_keeps_original_sources():
    pack = ResearchPack(
        topic="t",
        claims=[
            {
                "claim": "claim text",
                "source_url": "https://example.com",
                "source_title": "Example",
                "publisher": "Example",
                "retrieved_at": "2026-08-16T00:00:00+08:00",
                "source_type": "official_doc",
                "confidence": 0.8,
            }
        ],
        sources=["https://example.com"],
    )
    model = RecordingModel(pack)
    skill = ResearchSkill(model, fetcher=None, search=None)

    result = await skill.run("t", ["https://example.com"])

    assert result.search_hits == []
    assert "search_results" in model.user_payload

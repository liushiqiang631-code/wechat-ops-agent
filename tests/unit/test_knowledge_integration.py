from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.domain.models import (
    ArticleDocument,
    ArticleSection,
    ResearchPack,
    SourceSnapshot,
    VisualItem,
    VisualPlan,
    WebSearchResult,
)
from app.services.images.assets import AssetMaterializer
from app.services.knowledge import KnowledgeBaseClient, KnowledgeResults, KnowledgeUnavailable
from app.services.storage.artifacts import ArtifactStore
from app.skills.research import ResearchSkill
from app.skills.visual_planning import VisualPlanningSkill

BASE = "http://127.0.0.1:8010"
IMAGE_ID = "a" * 32
CONTENT = "芒果采后需根据树势安排水肥管理。"
PNG = b"\x89PNG\r\n\x1a\nfixture"


def settings():
    return Settings(
        _env_file=None, knowledge_base_enabled=True, knowledge_base_token="fixture-token"
    )


def results():
    return KnowledgeResults.model_validate(
        {
            "chunks": [
                {
                    "source_id": "mango-1",
                    "title": "采后管理",
                    "library": "农业技术库",
                    "content": CONTENT,
                    "content_hash": hashlib.sha256(CONTENT.encode()).hexdigest(),
                }
            ],
            "images": [
                {
                    "id": IMAGE_ID,
                    "name": "芒果.png",
                    "folder_name": "芒果",
                    "mime": "image/png",
                    "width": 100,
                    "height": 80,
                    "size": len(PNG),
                }
            ],
        }
    )


def article():
    return ArticleDocument(
        titles=["芒果采后管理"],
        selected_title="芒果采后管理",
        digest="树势管理",
        audience="种植户",
        sections=[ArticleSection(type="figure", caption="芒果果园")],
        ending="观察树势，再安排管理。",
    )


class Model:
    async def generate_structured(self, *, system, user, response_model):
        payload = json.loads(user)
        if response_model is ResearchPack:
            snapshot = payload["source_snapshots"][0]
            self.payload = payload
            return SimpleNamespace(
                data=ResearchPack.model_validate(
                    {
                        "topic": "芒果采后管理",
                        "sources": [snapshot["url"]],
                        "claims": [
                            {
                                "claim": CONTENT,
                                "source_url": snapshot["url"],
                                "source_title": snapshot["title"],
                                "publisher": "农业知识库",
                                "retrieved_at": snapshot["retrieved_at"],
                                "source_type": "knowledge_base",
                                "confidence": 0.8,
                                "quote_or_evidence": CONTENT,
                            }
                        ],
                    }
                )
            )
        assert payload["context"]["knowledge_images"][0]["id"] == IMAGE_ID
        return SimpleNamespace(
            data=VisualPlan(
                items=[
                    VisualItem(
                        kind="concept",
                        placement="采后管理",
                        purpose="解释树势观察",
                        prompt_or_source="芒果采后管理",
                        source="knowledge_base",
                        knowledge_image_id=IMAGE_ID,
                        caption="芒果果园",
                    ),
                    VisualItem(
                        kind="concept",
                        placement="正文",
                        purpose="未知素材",
                        prompt_or_source="不应采用",
                        source="knowledge_base",
                        knowledge_image_id="b" * 32,
                    ),
                ]
            )
        )


class Knowledge:
    async def search(self, *args, **kwargs):
        return results()

    snapshots = KnowledgeBaseClient.snapshots
    public_url = "https://kb.xunshanshengwu.cn"
    image_url = KnowledgeBaseClient.image_url

    async def download_image(self, identifier, *, max_bytes):
        assert identifier == IMAGE_ID
        return PNG


class NoExternal:
    async def search(self, *args, **kwargs):
        pytest.fail("knowledge hit must avoid unnecessary web search")

    async def generate(self, *args, **kwargs):
        pytest.fail("knowledge image must avoid paid image generation")


@respx.mock
@pytest.mark.asyncio
async def test_connection_uses_token_and_never_follows_redirects_or_leaks_secret():
    route = respx.post(BASE + "/api/materials/search").mock(
        return_value=httpx.Response(200, json=results().model_dump())
    )
    client = KnowledgeBaseClient(settings())
    assert (await client.search("芒果")).chunks[0].content == CONTENT
    assert route.calls[0].request.headers["X-Knowledge-Token"] == "fixture-token"
    route.mock(return_value=httpx.Response(302, headers={"Location": "https://other.example/"}))
    with pytest.raises(KnowledgeUnavailable) as captured:
        await client.search("芒果")
    assert "fixture-token" not in str(captured.value)
    assert "knowledge_base_token" not in settings().public_dict()
    with pytest.raises(ValueError):
        KnowledgeBaseClient(Settings(_env_file=None, knowledge_base_api_url="http://other.example"))


@pytest.mark.asyncio
async def test_research_prioritizes_local_snapshots_and_preserves_provenance():
    model = Model()
    pack = await ResearchSkill(model, knowledge=Knowledge()).run(
        "芒果采后管理", [], search=NoExternal()
    )
    assert pack.claims[0].source_type == "knowledge_base"
    assert pack.claims[0].source_snapshot_hash == hashlib.sha256(CONTENT.encode()).hexdigest()
    assert model.payload["external_content_trust"] == "untrusted"
    assert model.payload["source_priority"] == "knowledge_base_first"
    assert pack.source_snapshots[0].content_excerpt == CONTENT
    assert "source_snapshots" not in ResearchPack.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_planning_and_materialization_use_real_local_bytes_without_external_images(tmp_path):
    knowledge = Knowledge()
    plan = await VisualPlanningSkill(Model(), knowledge=knowledge).run(article(), {})
    assert len(plan.items) == 1
    assert plan.items[0].provider == "planned"
    materializer = AssetMaterializer(
        ArtifactStore(tmp_path / "outputs"),
        settings(),
        ai_generator=NoExternal(),
        search=NoExternal(),
        knowledge=knowledge,
    )
    manifest, updated = await materializer.materialize("task-1", plan, article())
    record = manifest.items[0]
    assert record.source == "knowledge_base"
    assert record.status == "ready"
    assert (tmp_path / "outputs/task-1/assets/img-00.png").read_bytes() == PNG
    assert record.sha256 == hashlib.sha256(PNG).hexdigest()
    assert IMAGE_ID in record.source_url
    assert updated.sections[0].asset_id == record.asset_id


@pytest.mark.asyncio
async def test_knowledge_outage_falls_back_to_fetched_sources_and_records_limitation():
    class Unavailable:
        async def search(self, *args, **kwargs):
            raise KnowledgeUnavailable("知识库暂时无法连接")

    class Fetcher:
        async def fetch(self, url):
            data = Knowledge().snapshots(results())[0].model_dump()
            return SourceSnapshot.model_validate({**data, "url": "https://agri.example/source"})

    pack = await ResearchSkill(Model(), fetcher=Fetcher(), knowledge=Unavailable()).run(
        "芒果采后管理", ["https://agri.example/source"]
    )
    assert "知识库暂时无法连接" in pack.limitations
    assert str(pack.claims[0].source_url) == "https://agri.example/source"


@pytest.mark.asyncio
async def test_no_knowledge_or_external_evidence_stops_before_model_call():
    class Empty:
        async def search(self, *args, **kwargs):
            return KnowledgeResults()

        def snapshots(self, result):
            return []

    with pytest.raises(ValueError, match="没有可核验"):
        await ResearchSkill(NoExternal(), knowledge=Empty()).run("芒果管理", [])


@pytest.mark.asyncio
async def test_timely_topic_checks_external_sources_even_with_local_hits():
    class Search:
        called = False

        async def search(self, query):
            self.called = True
            return WebSearchResult(query=query)

    search = Search()
    await ResearchSkill(Model(), knowledge=Knowledge()).run("今年芒果管理政策", [], search=search)
    assert search.called


@pytest.mark.asyncio
async def test_deleted_local_image_falls_back_and_records_actual_provider(tmp_path):
    class Deleted(Knowledge):
        async def download_image(self, *args, **kwargs):
            raise KnowledgeUnavailable("图片不存在")

    class Generator:
        async def generate(self, *args, **kwargs):
            return SimpleNamespace(image_bytes=PNG, content_type="image/png", fallback_used=False)

    plan = await VisualPlanningSkill(Model(), knowledge=Knowledge()).run(article(), {})
    materializer = AssetMaterializer(
        ArtifactStore(tmp_path / "fallback"),
        settings(),
        knowledge=Deleted(),
        ai_generator=Generator(),
    )
    manifest, _ = await materializer.materialize("task-2", plan, article())
    assert manifest.items[0].status == "ready"
    assert manifest.items[0].source == "ai_generated"


def test_changed_source_hash_is_not_accepted_as_a_snapshot():
    data = results()
    data.chunks[0].content = "已被改写的内容"
    assert KnowledgeBaseClient(settings()).snapshots(data) == []


@pytest.mark.asyncio
async def test_thin_local_hit_triggers_real_search_and_keeps_both_originals():
    events = []

    class Local(Knowledge):
        async def search(self, *args, **kwargs):
            events.append("knowledge")
            return results()

    class Assess(Model):
        async def generate_structured(self, **kwargs):
            result = await super().generate_structured(**kwargs)
            events.append("research")
            result.data.supplemental_queries = ["农业推广 采后养分吸收原理"]
            return result

    class Search:
        async def search(self, query):
            events.append("web_search")
            assert "养分吸收原理" in query
            return WebSearchResult(query=query, hits=[{
                "url": "https://agri.example/principles", "title": "养分吸收原理"
            }])

    class Fetcher:
        async def fetch(self, url):
            events.append("fetch")
            data = Knowledge().snapshots(results())[0].model_dump(mode="json")
            return SourceSnapshot.model_validate({**data, "url": url})

    pack = await ResearchSkill(Assess(), knowledge=Local(), fetcher=Fetcher()).run(
        "芒果采后管理", [], search=Search()
    )
    assert events == ["knowledge", "research", "web_search", "fetch", "research"]
    assert len(pack.source_snapshots) == 2
    assert str(pack.source_snapshots[1].url) == "https://agri.example/principles"
    assert len(pack.search_hits) == 1


@pytest.mark.asyncio
async def test_claim_binding_keeps_matching_chunk_when_document_url_is_shared():
    class Multi(Knowledge):
        async def search(self, *args, **kwargs):
            data = results()
            other = "同一文档的第二段，只介绍包装。"
            data.chunks.append(data.chunks[0].model_copy(update={
                "content": other, "content_hash": hashlib.sha256(other.encode()).hexdigest(),
            }))
            return data

    pack = await ResearchSkill(Model(), knowledge=Multi()).run("芒果", [])
    assert len(pack.source_snapshots) == 2
    assert pack.claims[0].source_snapshot_hash == hashlib.sha256(CONTENT.encode()).hexdigest()


@pytest.mark.asyncio
async def test_failed_local_and_web_images_fall_back_to_ai_without_stopping_article(tmp_path):
    events = []

    class Deleted(Knowledge):
        async def download_image(self, *args, **kwargs):
            events.append("knowledge")
            raise KnowledgeUnavailable("图片已删除")

    class EmptyWeb:
        async def search(self, *args, **kwargs):
            events.append("web")
            return []

    class Generator:
        async def generate(self, *args, **kwargs):
            events.append("ai")
            return SimpleNamespace(image_bytes=PNG, content_type="image/png", fallback_used=False)

    plan = await VisualPlanningSkill(Model(), knowledge=Knowledge()).run(article(), {})
    manifest, updated = await AssetMaterializer(
        ArtifactStore(tmp_path / "fallback"), settings(), knowledge=Deleted(),
        search=EmptyWeb(), ai_generator=Generator(),
    ).materialize("task-3", plan, article())
    assert events == ["knowledge", "web", "ai"]
    assert manifest.items[0].status == "ready"
    assert manifest.items[0].source == "ai_generated"
    assert "AI示意图" in updated.sections[0].caption


@pytest.mark.asyncio
async def test_unavailable_images_leave_readable_copy_instead_of_broken_placeholders(tmp_path):
    class Deleted(Knowledge):
        async def download_image(self, *args, **kwargs):
            raise KnowledgeUnavailable("图片已删除")

    plan = await VisualPlanningSkill(Model(), knowledge=Knowledge()).run(article(), {})
    manifest, updated = await AssetMaterializer(
        ArtifactStore(tmp_path / "missing"), settings(), knowledge=Deleted(),
    ).materialize("task-4", plan, article())
    assert manifest.items[0].status == "failed"
    assert not any(section.type == "figure" for section in updated.sections)
    assert updated.ending == article().ending

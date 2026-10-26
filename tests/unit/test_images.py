from __future__ import annotations

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.domain.models import ArticleDocument, ArticleSection, VisualItem, VisualPlan
from app.services.images.assets import AssetMaterializer
from app.services.images.siliconflow import (
    GeneratedImage,
    SiliconFlowImageClient,
    SiliconFlowImageError,
)
from app.services.images.websearch import WebImageCandidate, WikimediaImageSearch
from app.services.storage.artifacts import ArtifactStore

BASE = "https://api.siliconflow.cn/v1"


def settings_with_sf() -> Settings:
    return Settings(
        _env_file=None,
        image_model_provider="siliconflow",
        siliconflow_api_key="sf-secret-key",
        siliconflow_api_base=BASE,
        siliconflow_image_model="Qwen/Qwen-Image-3.0-Pro",
    )


@respx.mock
@pytest.mark.asyncio
async def test_siliconflow_falls_back_to_available_qwen_image_model():
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "Qwen/Qwen-Image"},
                    {"id": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"},
                ]
            },
        )
    )
    client = SiliconFlowImageClient(settings_with_sf())

    model, fallback = await client.resolve_model()

    assert model == "Qwen/Qwen-Image"
    assert fallback is True


@respx.mock
@pytest.mark.asyncio
async def test_siliconflow_generate_uses_configured_model_and_downloads_url():
    models_route = respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "Qwen/Qwen-Image-3.0-Pro"}, {"id": "Qwen/Qwen-Image"}]},
        )
    )
    route = respx.post(f"{BASE}/images/generations").mock(
        return_value=httpx.Response(
            200,
            json={
                "images": [{"url": "https://cdn.siliconflow.example/img.png"}],
                "seed": 42,
            },
        )
    )
    client = SiliconFlowImageClient(settings_with_sf())

    result = await client.generate("一只猫在键盘上打代码", image_size="1024x1024")

    assert isinstance(result, GeneratedImage)
    assert result.url == "https://cdn.siliconflow.example/img.png"
    assert result.model == "Qwen/Qwen-Image-3.0-Pro"
    assert result.fallback_used is False
    request = route.calls[0].request
    assert b'"model":"Qwen/Qwen-Image-3.0-Pro"' in request.content
    assert '"一只猫在键盘上打代码"'.encode() in request.content
    assert models_route.called


@respx.mock
@pytest.mark.asyncio
async def test_siliconflow_auth_failure_is_not_retryable():
    respx.post(f"{BASE}/images/generations").mock(
        return_value=httpx.Response(401, text="Invalid token")
    )
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "Qwen/Qwen-Image"}]})
    )
    client = SiliconFlowImageClient(settings_with_sf())

    with pytest.raises(SiliconFlowImageError) as captured:
        await client.generate("prompt")

    assert captured.value.code == "authentication_failed"
    assert captured.value.retryable is False
    assert "sf-secret-key" not in str(captured.value)


def test_siliconflow_without_key_raises_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    settings = Settings(_env_file=None, image_model_provider="siliconflow")
    client = SiliconFlowImageClient(settings)

    with pytest.raises(SiliconFlowImageError) as captured:
        client._headers()

    assert captured.value.code == "not_configured"


@respx.mock
@pytest.mark.asyncio
async def test_wikimedia_search_filters_licenses_and_small_images():
    respx.get("https://commons.wikimedia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "1": {
                            "title": "File:langgraph diagram.png",
                            "imageinfo": [
                                {
                                    "mime": "image/png",
                                    "width": 1920,
                                    "height": 1080,
                                    "url": "https://upload.wikimedia.org/example.png",
                                    "thumburl": "https://upload.wikimedia.org/thumb.png",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:langgraph",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                        "Artist": {"value": "<a>张三</a>"},
                                    },
                                }
                            ],
                        },
                        "2": {
                            "title": "File:excluded nc.png",
                            "imageinfo": [
                                {
                                    "mime": "image/png",
                                    "width": 900,
                                    "height": 600,
                                    "url": "https://upload.wikimedia.org/excluded.png",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC BY-NC 4.0"},
                                        "Artist": {"value": "李四"},
                                    },
                                }
                            ],
                        },
                        "3": {
                            "title": "File:tiny.png",
                            "imageinfo": [
                                {
                                    "mime": "image/png",
                                    "width": 320,
                                    "height": 240,
                                    "url": "https://upload.wikimedia.org/tiny.png",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC0"},
                                    },
                                }
                            ],
                        },
                    }
                }
            },
        )
    )
    search = WikimediaImageSearch()

    candidates = await search.search("langgraph 架构", limit=4)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, WebImageCandidate)
    assert candidate.license_name == "CC BY-SA 4.0"
    assert candidate.author == "张三"
    assert candidate.thumb_url == "https://upload.wikimedia.org/thumb.png"


@respx.mock
@pytest.mark.asyncio
async def test_materializer_generates_downloads_and_attaches_assets(tmp_path):
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "Qwen/Qwen-Image"}]}
        )
    )
    respx.post(f"{BASE}/images/generations").mock(
        return_value=httpx.Response(
            200,
            json={"images": [{"url": "https://cdn.siliconflow.example/generated.png"}]},
        )
    )
    respx.get("https://cdn.siliconflow.example/generated.png").mock(
        return_value=httpx.Response(
            200,
            # CDNs often serve generated images as octet-stream; the materializer
            # must sniff the PNG magic bytes instead of trusting the header.
            content=b"\x89PNG\r\n\x1a\nfake-image-bytes",
            headers={"content-type": "application/octet-stream"},
        )
    )
    settings = settings_with_sf()
    store = ArtifactStore(tmp_path / "outputs")
    materializer = AssetMaterializer(
        store,
        settings,
        ai_generator=SiliconFlowImageClient(settings),
        search=WikimediaImageSearch(),
    )
    article = ArticleDocument(
        titles=["标题"],
        selected_title="标题",
        digest="摘要",
        audience="开发者",
        sections=[
            ArticleSection(type="paragraph", content="正文一"),
            ArticleSection(type="figure", caption="架构示意图"),
            ArticleSection(type="paragraph", content="正文二"),
        ],
        references=[],
        ending="结尾",
    )
    plan = VisualPlan(
        items=[
            VisualItem(
                kind="concept",
                placement="第一节后",
                purpose="配图",
                prompt_or_source="a network diagram of agent architecture",
                source="ai_generated",
                caption="架构示意图",
            ),
            VisualItem(
                kind="mermaid",
                placement="机制后",
                purpose="流程图",
                prompt_or_source="flowchart LR; A --> B",
                provider="deterministic",
            ),
        ]
    )

    manifest, updated = await materializer.materialize("task-1", plan, article)

    assert manifest.ai_generation_configured is True
    ready = [item for item in manifest.items if item.status == "ready"]
    assert len(ready) == 1
    assert ready[0].source == "ai_generated"
    assert ready[0].sha256 is not None
    assert (tmp_path / "outputs" / "task-1" / "assets" / "img-00.png").exists()
    figure = next(section for section in updated.sections if section.type == "figure")
    assert figure.asset_id == "img-00"
    # deterministic diagrams never become raster assets
    assert all(item.status != "ready" or item.kind != "mermaid" for item in manifest.items)


@respx.mock
@pytest.mark.asyncio
async def test_materializer_saves_base64_image_bytes_directly(tmp_path):
    from app.services.images.siliconflow import GeneratedImage

    class FakeGenerator:
        provider_name = "dashscope"

        async def generate(self, prompt, *, image_size=None):
            return GeneratedImage(
                url="",
                model="qwen-image-3.0-pro",
                image_bytes=b"\x89PNG\r\n\x1a\nbase64-png",
                content_type="image/png",
            )

    settings = Settings(
        _env_file=None,
        image_model_provider="dashscope",
        dashscope_inter_request_delay=0,
    )
    store = ArtifactStore(tmp_path / "outputs")
    materializer = AssetMaterializer(store, settings, ai_generator=FakeGenerator())
    article = ArticleDocument(
        titles=["标题"],
        selected_title="标题",
        digest="摘要",
        audience="开发者",
        sections=[
            ArticleSection(type="paragraph", content="正文"),
            ArticleSection(type="figure", caption="示意图"),
        ],
        references=[],
        ending="结尾",
    )
    plan = VisualPlan(
        items=[
            VisualItem(
                kind="concept",
                placement="第一节后",
                purpose="配图",
                prompt_or_source="diagram",
                source="ai_generated",
                caption="示意图",
            )
        ]
    )

    manifest, updated = await materializer.materialize("task-3", plan, article)

    assert manifest.items[0].status == "ready"
    assert manifest.items[0].provider == "dashscope"
    assert (tmp_path / "outputs" / "task-3" / "assets" / "img-00.png").read_bytes() == (
        b"\x89PNG\r\n\x1a\nbase64-png"
    )
    figure = next(section for section in updated.sections if section.type == "figure")
    assert figure.asset_id == "img-00"


@respx.mock
@pytest.mark.asyncio
async def test_materializer_without_providers_marks_items_skipped(tmp_path):
    store = ArtifactStore(tmp_path / "outputs")
    materializer = AssetMaterializer(store, Settings(_env_file=None))
    plan = VisualPlan(
        items=[
            VisualItem(
                kind="concept",
                placement="第一节后",
                purpose="配图",
                prompt_or_source="query",
                source="web_search",
            )
        ]
    )
    article = ArticleDocument(
        titles=["标题"],
        selected_title="标题",
        digest="摘要",
        audience="开发者",
        sections=[ArticleSection(type="paragraph", content="正文")],
        references=[],
        ending="结尾",
    )

    manifest, updated = await materializer.materialize("task-2", plan, article)

    assert manifest.items[0].status == "skipped"
    assert updated is article


@pytest.mark.asyncio
async def test_review_draft_gallery_failure_never_falls_back_to_paid_or_web(tmp_path):
    class Knowledge:
        def image_url(self, identifier):
            return 'https://kb.example/' + identifier
        async def download_image(self, *args, **kwargs):
            raise ValueError('deleted image')
    class Forbidden:
        async def generate(self, *args, **kwargs):
            pytest.fail('review-draft gallery cannot generate images')
        async def search(self, *args, **kwargs):
            pytest.fail('review-draft gallery cannot search external images')
    materializer = AssetMaterializer(
        ArtifactStore(tmp_path / "outputs"),
        settings_with_sf(),
        ai_generator=Forbidden(),
        search=Forbidden(),
        knowledge=Knowledge(),
    )
    article = ArticleDocument(
        titles=["鱼教授"],
        selected_title="鱼教授",
        digest="摘要",
        audience="种植户",
        ending="结尾",
        sections=[
            ArticleSection(type="figure", asset_id="invented", caption="占位"),
        ],
    )
    plan = VisualPlan(
        items=[
            VisualItem(
                kind="concept",
                placement="正文",
                purpose="配图",
                prompt_or_source="图库",
                source="knowledge_base",
                knowledge_image_id="a" * 32,
            )
        ]
    )
    manifest, updated = await materializer.materialize_knowledge_only(
        "review-draft", plan, article
    )
    assert manifest.items[0].status == 'failed'
    assert not any(s.type == 'figure' for s in updated.sections)

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime

from app.config.settings import Settings
from app.domain.models import (
    ArticleDocument,
    ArticleSection,
    AssetManifest,
    AssetRecord,
    VisualPlan,
)
from app.services.citations.fetcher import SafeSourceFetcher
from app.services.images.websearch import WikimediaImageSearch
from app.services.storage.artifacts import ArtifactStore

ASSET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
MAX_IMAGE_BYTES = 15 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _sniff_image_type(body: bytes) -> str | None:
    """Detect the image type from magic bytes (independent of HTTP headers)."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


class AssetMaterializer:
    """Turn a VisualPlan into real image files under ``outputs/<task>/assets/``.

    Best-effort by design: a failed image generation or search never blocks the
    article. Every attempt is recorded with provenance (source, license, author)
    in the ``assets`` artifact for human review.
    """

    def __init__(
        self,
        artifacts: ArtifactStore,
        settings: Settings,
        ai_generator: object | None = None,
        search: WikimediaImageSearch | None = None,
    ):
        self.artifacts = artifacts
        self.settings = settings
        self.ai_generator = ai_generator
        self.search = search

    @property
    def _inter_request_delay(self) -> float:
        # qwen-image-3.0-pro on Bailian is rate limited to 1 RPM; sequential
        # generations must pause between requests.
        if self.settings.image_model_provider == "dashscope":
            return max(0.0, self.settings.dashscope_inter_request_delay)
        return 0.0

    # 封面取 2:1 适配公众号头图裁切，内文配图 16:9，避免正方形大图撑版面
    KIND_IMAGE_SIZES = {"cover": "1024x512"}
    DEFAULT_IMAGE_SIZE = "1024x576"

    # -- public ------------------------------------------------------------

    async def materialize(
        self, task_id: str, plan: VisualPlan, article: ArticleDocument
    ) -> tuple[AssetManifest, ArticleDocument]:
        items = [
            item for item in plan.items if item.source in {"ai_generated", "web_search"}
        ]
        records: list[AssetRecord] = []
        for index, item in enumerate(items):
            if index > 0 and self._inter_request_delay > 0:
                await asyncio.sleep(self._inter_request_delay)
            asset_id = f"img-{index:02d}"
            if item.source == "ai_generated" and self.ai_generator is not None:
                records.append(await self._generate(task_id, asset_id, item))
            elif item.source == "web_search" and self.search is not None:
                records.append(await self._search_and_download(task_id, asset_id, item))
            else:
                records.append(
                    AssetRecord(
                        asset_id=asset_id,
                        kind=item.kind,
                        caption=item.caption,
                        source=item.source,
                        query_or_prompt=item.prompt_or_source,
                        status="skipped",
                        error="image provider is not configured",
                    )
                )
        manifest = AssetManifest(
            task_id=task_id,
            items=records,
            ai_generation_configured=self.ai_generator is not None,
            web_search_configured=self.search is not None,
        )
        updated = self._attach_to_article(article, records)
        return manifest, updated

    # -- acquisition -------------------------------------------------------

    async def _generate(self, task_id: str, asset_id: str, item) -> AssetRecord:
        provider = getattr(self.ai_generator, "provider_name", "ai_generated")
        try:
            generated = await self.ai_generator.generate(
                item.prompt_or_source,
                image_size=self.KIND_IMAGE_SIZES.get(item.kind, self.DEFAULT_IMAGE_SIZE),
            )
            if generated.image_bytes:
                record = await self._save_bytes(task_id, asset_id, item, generated, provider)
            else:
                record = await self._download(
                    task_id,
                    asset_id,
                    item,
                    source_url=generated.url,
                    provider=provider,
                    license_name="AI generated",
                )
            if record.status == "ready" and generated.fallback_used:
                record.error = "configured model unavailable; fell back to Qwen/Qwen-Image"
            return record
        except Exception as error:
            return AssetRecord(
                asset_id=asset_id,
                kind=item.kind,
                caption=item.caption,
                source="ai_generated",
                provider=provider,
                query_or_prompt=item.prompt_or_source,
                status="failed",
                error=f"{type(error).__name__}: {error}",
                created_at=datetime.now().astimezone(),
            )

    async def _save_bytes(
        self, task_id: str, asset_id: str, item, generated, provider: str
    ) -> AssetRecord:
        content_type = generated.content_type or _sniff_image_type(generated.image_bytes or b"")
        base = AssetRecord(
            asset_id=asset_id,
            kind=item.kind,
            caption=item.caption,
            source="ai_generated",
            provider=provider,
            query_or_prompt=item.prompt_or_source,
            license_name="AI generated",
            created_at=datetime.now().astimezone(),
        )
        if content_type not in ALLOWED_CONTENT_TYPES:
            return base.model_copy(
                update={"status": "failed", "error": f"unexpected image type {content_type}"}
            )
        if len(generated.image_bytes or b"") > MAX_IMAGE_BYTES:
            return base.model_copy(
                update={"status": "failed", "error": f"image exceeds {MAX_IMAGE_BYTES} bytes"}
            )
        extension = CONTENT_TYPE_EXTENSIONS[content_type]
        asset_dir = self.artifacts.root / task_id / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        destination = asset_dir / f"{asset_id}.{extension}"
        destination.write_bytes(generated.image_bytes or b"")
        return base.model_copy(
            update={
                "status": "ready",
                "local_path": str(destination),
                "file_name": destination.name,
                "content_type": content_type,
                "sha256": hashlib.sha256(generated.image_bytes or b"").hexdigest(),
            }
        )

    async def _search_and_download(self, task_id: str, asset_id: str, item) -> AssetRecord:
        try:
            candidates = await self.search.search(item.prompt_or_source, limit=3)
            if not candidates:
                return AssetRecord(
                    asset_id=asset_id,
                    kind=item.kind,
                    caption=item.caption,
                    source="web_search",
                    provider="wikimedia",
                    query_or_prompt=item.prompt_or_source,
                    status="failed",
                    error="no usable image found for the query",
                    created_at=datetime.now().astimezone(),
                )
            chosen = candidates[0]
            record = await self._download(
                task_id,
                asset_id,
                item,
                source_url=chosen.original_url,
                provider="wikimedia",
                license_name=chosen.license_name,
                author=chosen.author,
            )
            return record
        except Exception as error:
            return AssetRecord(
                asset_id=asset_id,
                kind=item.kind,
                caption=item.caption,
                source="web_search",
                provider="wikimedia",
                query_or_prompt=item.prompt_or_source,
                status="failed",
                error=f"{type(error).__name__}: {error}",
                created_at=datetime.now().astimezone(),
            )

    async def _download(
        self,
        task_id: str,
        asset_id: str,
        item,
        *,
        source_url: str,
        provider: str,
        license_name: str,
        author: str | None = None,
    ) -> AssetRecord:
        base = AssetRecord(
            asset_id=asset_id,
            kind=item.kind,
            caption=item.caption,
            source=item.source,
            provider=provider,
            query_or_prompt=item.prompt_or_source,
            source_url=source_url,
            license_name=license_name,
            author=author,
            created_at=datetime.now().astimezone(),
        )
        fetched = await SafeSourceFetcher().fetch_bytes(
            source_url,
            max_bytes=MAX_IMAGE_BYTES,
        )
        body = fetched.body
        declared = fetched.content_type
        # Some CDNs (e.g. SiliconFlow image URLs) serve bytes as
        # application/octet-stream; sniff the magic bytes before trusting the
        # declared content type.
        content_type = _sniff_image_type(body) or declared
        if content_type not in ALLOWED_CONTENT_TYPES:
            return base.model_copy(
                update={
                    "status": "failed",
                    "error": f"unexpected content type {declared}",
                }
            )
        if len(body) > MAX_IMAGE_BYTES:
            return base.model_copy(
                update={
                    "status": "failed",
                    "error": f"image exceeds {MAX_IMAGE_BYTES} bytes",
                }
            )
        if content_type not in ALLOWED_CONTENT_TYPES:
            return base.model_copy(
                update={"status": "failed", "error": f"unexpected content type {content_type}"}
            )
        extension = CONTENT_TYPE_EXTENSIONS[content_type]
        asset_dir = self.artifacts.root / task_id / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        destination = asset_dir / f"{asset_id}.{extension}"
        destination.write_bytes(body)
        return base.model_copy(
            update={
                "status": "ready",
                "local_path": str(destination),
                "file_name": destination.name,
                "content_type": content_type,
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )

    # -- article attachment ------------------------------------------------

    @staticmethod
    def _attach_to_article(
        article: ArticleDocument, records: list[AssetRecord]
    ) -> ArticleDocument:
        """Bind ready assets to figure sections (by order) or insert figures."""
        ready = [record for record in records if record.status == "ready"]
        if not ready:
            return article
        sections = list(article.sections)
        figure_indexes = [i for i, section in enumerate(sections) if section.type == "figure"]
        assigned: set[int] = set()
        for figure_index, record in zip(figure_indexes, ready, strict=False):
            sections[figure_index] = sections[figure_index].model_copy(
                update={"asset_id": record.asset_id, "caption": record.caption}
            )
            assigned.add(figure_index)
        remaining = [record for i, record in enumerate(ready) if i >= len(figure_indexes)]
        if not figure_indexes:
            # No figure sections from the writer: insert up to two figures at
            # deterministic positions so the article still has visuals.
            for offset, record in enumerate(remaining[:2]):
                insert_at = min(2 + offset, len(sections))
                sections.insert(
                    insert_at,
                    ArticleSection(
                        type="figure",
                        asset_id=record.asset_id,
                        caption=record.caption or "文章配图",
                    ),
                )
        return article.model_copy(update={"sections": sections})

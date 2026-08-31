from __future__ import annotations

from datetime import datetime

from app.domain.models import ResearchPack
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "research",
    "title": "权威研究",
    "description": "联网搜索 + 抓取官方来源并提炼可溯源事实，检测提示注入。",
    "category": "pipeline",
    "version": "1.1.0",
    "builtin": True,
    "locked": True,
}


class ResearchSkill:
    version = "1.1.0"

    def __init__(
        self,
        model,
        fetcher=None,
        search=None,
        max_extra_sources: int = 8,
        max_sources: int = 20,
    ):
        self.model = model
        self.fetcher = fetcher
        self.search = search
        self.max_extra_sources = max_extra_sources
        self.max_sources = max_sources

    async def run(
        self, topic: str, source_urls: list[str], *, search=None
    ) -> ResearchPack:
        search_service = search if search is not None else self.search
        snapshots = []
        fetch_errors = []
        search_result = None
        if search_service is not None:
            search_result = await search_service.search(topic)
            known = set(source_urls)
            extra = [
                str(hit.url)
                for hit in search_result.hits
                if str(hit.url) not in known
            ][: self.max_extra_sources]
            source_urls = [*source_urls, *extra]
        source_urls = source_urls[: self.max_sources]
        if self.fetcher is not None:
            for url in source_urls:
                try:
                    snapshot = await self.fetcher.fetch(url)
                    snapshots.append(snapshot.model_dump(mode="json"))
                except Exception as error:
                    fetch_errors.append({"url": url, "error": type(error).__name__})
        result = await self.model.generate_structured(
            system=load_prompt("research"),
            user=compact_json(
                {
                    "topic": topic,
                    "source_urls": source_urls,
                    "source_snapshots": snapshots,
                    "fetch_errors": fetch_errors,
                    "search_results": (
                        search_result.model_dump(mode="json") if search_result else None
                    ),
                    "external_content_trust": "untrusted",
                }
            ),
            response_model=ResearchPack,
        )
        pack = result.data
        if snapshots:
            snapshot_by_url = {
                str(snapshot["url"]).rstrip("/"): snapshot for snapshot in snapshots
            }
            supported_claims = []
            for claim in pack.claims:
                snapshot = snapshot_by_url.get(str(claim.source_url).rstrip("/"))
                if snapshot is None:
                    continue
                supported_claims.append(
                    claim.model_copy(
                        update={
                            "source_snapshot_hash": snapshot["content_hash"],
                            "retrieved_at": datetime.fromisoformat(snapshot["retrieved_at"]),
                            "prompt_injection_flags": snapshot["prompt_injection_flags"],
                        }
                    )
                )
            if not supported_claims:
                raise ValueError("research returned no claims backed by fetched snapshots")
            pack = pack.model_copy(
                update={
                    "claims": supported_claims,
                    "sources": list(dict.fromkeys(claim.source_url for claim in supported_claims)),
                }
            )
        if search_result is not None:
            pack = pack.model_copy(update={"search_hits": search_result.hits})
        return pack

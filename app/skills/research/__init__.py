from __future__ import annotations

from datetime import datetime

from app.domain.models import ResearchPack, SourceSnapshot
from app.services.knowledge import KnowledgeUnavailable
from app.skills.common import compact_json, load_prompt

SKILL_META = {
    "name": "research",
    "title": "权威研究",
    "description": "先查知识库，资料不足再联网补充；保留原文供写作核对，内部资料缺口不写入成稿。",
    "category": "pipeline",
    "version": "1.3.1",
    "builtin": True,
    "locked": True,
}


class ResearchSkill:
    version = "1.3.1"

    def __init__(
        self,
        model,
        fetcher=None,
        search=None,
        max_extra_sources: int = 8,
        max_sources: int = 20,
        knowledge=None,
    ):
        self.model = model
        self.fetcher = fetcher
        self.search = search
        self.max_extra_sources = max_extra_sources
        self.max_sources = max_sources
        self.knowledge = knowledge

    async def run(self, topic: str, source_urls: list[str], *, search=None) -> ResearchPack:
        search_service = search if search is not None else self.search
        snapshots = []
        knowledge_snapshots = []
        limitations = []
        fetch_errors = []
        search_result = None
        if self.knowledge is not None:
            try:
                local = await self.knowledge.search(topic, image_limit=0)
                knowledge_snapshots = self.knowledge.snapshots(local)
                snapshots.extend(
                    snapshot.model_dump(mode="json") for snapshot in knowledge_snapshots
                )
                limitations.extend(local.warnings)
                if not knowledge_snapshots:
                    limitations.append("知识库未找到与本选题匹配的正文，已尝试补充权威来源")
            except KnowledgeUnavailable as error:
                limitations.append(str(error))
        timely = any(
            term in topic
            for term in (
                "最新",
                "今年",
                "今天",
                "近期",
                "政策",
                "登记",
                "补贴",
                "行情",
                "价格",
                "预警",
            )
        )
        supplement = not knowledge_snapshots or timely
        if search_service is not None and supplement:
            search_result = await search_service.search(topic)
            known = set(source_urls)
            extra = [str(hit.url) for hit in search_result.hits if str(hit.url) not in known][
                : self.max_extra_sources
            ]
            source_urls = [*source_urls, *extra]
        source_urls = source_urls[: self.max_sources]
        if self.fetcher is not None:
            for url in source_urls:
                try:
                    snapshot = await self.fetcher.fetch(url)
                    snapshots.append(snapshot.model_dump(mode="json"))
                except Exception as error:
                    fetch_errors.append({"url": url, "error": type(error).__name__})
        if self.knowledge is not None and not snapshots:
            raise ValueError("没有可核验的本地或外部正文，不能凭空生成农业研究材料")
        async def extract():
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
                        "source_priority": "knowledge_base_first",
                        "knowledge_source_urls": [
                            str(snapshot.url) for snapshot in knowledge_snapshots
                        ],
                        "knowledge_limitations": limitations,
                    }
                ),
                response_model=ResearchPack,
            )
            return result.data

        pack = await extract()
        # A local hit can still be too thin. Assess it first, then perform one bounded
        # real search pass for missing context instead of asking the writer to guess.
        if search_service is not None and search_result is None and pack.supplemental_queries:
            query = topic + " " + " ".join(pack.supplemental_queries)
            search_result = await search_service.search(query)
            known = {str(snapshot["url"]).rstrip("/") for snapshot in snapshots}
            extra = list(dict.fromkeys(
                str(hit.url) for hit in search_result.hits
                if str(hit.url).rstrip("/") not in known
            ))[: self.max_extra_sources]
            for url in extra[: max(0, self.max_sources - len(source_urls))]:
                source_urls.append(url)
                if self.fetcher is not None:
                    try:
                        snapshot = await self.fetcher.fetch(url)
                        snapshots.append(snapshot.model_dump(mode="json"))
                    except Exception as error:
                        fetch_errors.append({"url": url, "error": type(error).__name__})
            pack = await extract()
        if snapshots:
            snapshots_by_url = {}
            for snapshot in snapshots:
                snapshots_by_url.setdefault(str(snapshot["url"]).rstrip("/"), []).append(snapshot)
            supported_claims = []
            for claim in pack.claims:
                candidates = snapshots_by_url.get(str(claim.source_url).rstrip("/"), [])
                if not candidates:
                    continue
                # Multiple chunks can share one document URL. Keep the matching
                # original rather than silently rebinding every claim to the last chunk.
                quote = "".join((claim.quote_or_evidence or "").split())
                snapshot = next((
                    item for item in candidates
                    if quote and quote in "".join(item["content_excerpt"].split())
                ), None)
                if snapshot is None:
                    snapshot = next((
                        item for item in candidates
                        if item["content_hash"] == claim.source_snapshot_hash
                    ), candidates[0])
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
        local_urls = {str(snapshot.url) for snapshot in knowledge_snapshots}
        claims = [
            claim.model_copy(update={"source_type": "knowledge_base"})
            if str(claim.source_url) in local_urls
            else claim
            for claim in pack.claims
        ]
        pack = pack.model_copy(
            update={"claims": claims, "limitations": [*pack.limitations, *limitations],
                "source_snapshots": [SourceSnapshot.model_validate(item) for item in snapshots]}
        )
        return pack

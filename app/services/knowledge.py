"""Read-only connection to the agricultural knowledge service; no model calls."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import BaseModel, Field

from app.config.settings import Settings
from app.domain.models import SourceSnapshot


class KnowledgeImage(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str
    folder_name: str | None = None
    mime: str
    width: int
    height: int
    size: int


class KnowledgeChunk(BaseModel):
    source_id: str
    title: str
    library: str = ""
    source_name: str = ""
    section_path: str = ""
    content: str = Field(max_length=2400)
    content_hash: str


class KnowledgeResults(BaseModel):
    chunks: list[KnowledgeChunk] = Field(default_factory=list, max_length=12)
    images: list[KnowledgeImage] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list)


class KnowledgeUnavailable(RuntimeError):
    pass


class KnowledgeBaseClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.knowledge_base_api_url.rstrip("/")
        self.public_url = settings.knowledge_base_public_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            )
        ):
            raise ValueError("知识库地址必须使用 HTTPS 或本机回环地址")

    @property
    def headers(self) -> dict[str, str]:
        token = self.settings.knowledge_base_token
        return {"X-Knowledge-Token": token.get_secret_value() if token else ""}

    async def search(
        self, query: str, *, text_limit: int = 8, image_limit: int = 12
    ) -> KnowledgeResults:
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.knowledge_base_timeout, trust_env=False
            ) as client:
                response = await client.post(
                    self.base_url + "/api/materials/search",
                    headers=self.headers,
                    json={
                        "query": query[:500],
                        "text_limit": text_limit,
                        "image_limit": image_limit,
                    },
                )
                response.raise_for_status()
                if len(response.content) > 256 * 1024:
                    raise ValueError("oversized knowledge response")
                return KnowledgeResults.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise KnowledgeUnavailable("知识库暂时无法连接，已转入补充来源流程") from error

    def snapshots(self, results: KnowledgeResults) -> list[SourceSnapshot]:
        snapshots = []
        for chunk in results.chunks:
            digest = hashlib.sha256(chunk.content.encode()).hexdigest()
            if digest != chunk.content_hash:
                continue
            snapshots.append(
                SourceSnapshot(
                    url=self.public_url
                    + "/documents.html?"
                    + urlencode({"source": chunk.source_id}),
                    title=f"{chunk.library}｜{chunk.title}",
                    content_excerpt=chunk.content,
                    retrieved_at=datetime.now(UTC),
                    content_hash=digest,
                    content_type="text/plain",
                )
            )
        return snapshots

    def image_url(self, identifier: str) -> str:
        return self.public_url + "/api/gallery/images/" + identifier + "/content"

    async def download_image(self, identifier: str, *, max_bytes: int) -> bytes:
        if len(identifier) != 32 or any(char not in "0123456789abcdef" for char in identifier):
            raise KnowledgeUnavailable("无效的知识库图片编号")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.knowledge_base_timeout, trust_env=False
            ) as client:
                async with client.stream(
                    "GET",
                    self.base_url + f"/api/materials/images/{identifier}/content",
                    headers=self.headers,
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > max_bytes:
                            raise ValueError("oversized knowledge image")
                    return bytes(body)
        except (httpx.HTTPError, ValueError) as error:
            raise KnowledgeUnavailable("知识库图片读取失败") from error

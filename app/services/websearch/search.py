from __future__ import annotations

import base64
import logging
import re
from urllib.parse import parse_qs, quote, urlparse

import httpx

from app.config.settings import Settings
from app.domain.models import WebSearchHit, WebSearchResult

logger = logging.getLogger(__name__)

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_EMPHASIS = re.compile(r"[*_`]+")
# Bing result pages render lots of UI chrome (icons, sprites, "skip to content"
# links) that are not search results; these hosts and shapes are noise.
# Note: bing.com/ck/a redirect links ARE valid candidates (the fetcher follows
# the redirect and re-validates the final host), so only asset hosts and
# self-referencing search-page links are filtered out.
_NOISE_HOSTS = {
    "r.bing.com",
    "th.bing.com",
    "tse1.mm.bing.net",
    "tse2.mm.bing.net",
    "tse3.mm.bing.net",
    "tse4.mm.bing.net",
}
_NOISE_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".css", ".js", ".ico")
_NAV_TITLES = {
    "all",
    "search",
    "images",
    "videos",
    "maps",
    "news",
    "shopping",
    "more",
    "settings",
    "sign in",
    "see more",
    "flights",
    "hotels",
    "translate",
    "mail",
    "weather",
    "games",
    "filters",
    "tools",
    "feedback",
    "privacy",
}


def _clean_markdown(text: str) -> str:
    return " ".join(_EMPHASIS.sub("", text).split()).strip()


def _is_noise(url: str, title: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _NOISE_HOSTS:
        return True
    if host.endswith("bing.com"):
        # self-referencing search/copilot/nav links, and bare host links
        if parsed.path.startswith("/search") or parsed.path.startswith("/copilotsearch"):
            return True
        if parsed.path in {"", "/", "/?"}:
            return True
    if parsed.path.lower().endswith(_NOISE_SUFFIXES):
        return True
    lowered_title = title.lower()
    if lowered_title in {"skip to content", "close", "drop an image here", "image"}:
        return True
    if lowered_title in _NAV_TITLES or lowered_title.startswith(
        ("image ", "advertisement", "sponsored")
    ):
        return True
    return False


def decode_bing_redirect(raw_url: str) -> str:
    """Resolve Bing ``/ck/a`` redirect URLs to their real destinations.

    Bing wraps result links as ``bing.com/ck/a?...&u=<base64(destination)>``.
    When decoding fails the original URL is returned unchanged.
    """
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if "bing.com" not in host and "bing.net" not in host:
        return raw_url
    encoded = (parse_qs(parsed.query).get("u") or [None])[0]
    if not encoded:
        return raw_url
    # Bing currently emits both plain base64 values and an ``a1``-prefixed
    # variant. The latter must be stripped before decoding; otherwise the
    # bytes no longer begin with the destination URL and search results point
    # back to Bing rather than their source.
    candidates = [encoded]
    if encoded.startswith("a1"):
        candidates.append(encoded[2:])
    for candidate in candidates:
        try:
            decoded = base64.b64decode(candidate + "=" * (-len(candidate) % 4)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded.startswith(("http://", "https://")):
            return decoded
    return raw_url


class WebSearchService:
    """Web search for the agent without an API key.

    Uses the Jina Reader gateway (``r.jina.ai``) to render Bing result pages as
    clean markdown, then extracts real destination URLs (Bing redirects are
    decoded) with their titles and snippets. Results are untrusted data: the
    research skill treats them as candidate sources that go through the same
    SSRF-guarded fetcher as everything else.
    """

    provider_name = "jina_bing"
    GATEWAY = "https://r.jina.ai/http://www.bing.com/search?q={query}&count={count}"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def search(self, query: str, limit: int | None = None) -> WebSearchResult:
        limit = limit or self.settings.web_search_max_results
        url = self.GATEWAY.format(
            query=quote(query), count=max(1, min(limit, 20))
        )
        try:
            body = await self._get(url)
            hits = self._parse(body, limit=limit)
            return WebSearchResult(query=query, hits=hits, provider=self.provider_name)
        except Exception as error:
            logger.warning("web search failed for %r: %s", query, error)
            return WebSearchResult(
                query=query,
                provider=self.provider_name,
                error=f"{type(error).__name__}: {error}",
            )

    async def _get(self, url: str) -> str:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.web_search_timeout, connect=12.0),
            follow_redirects=True,
            headers={"User-Agent": "wechat-ops-agent/0.1 web-search"},
        )
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
        finally:
            if owns_client:
                await client.aclose()

    def _parse(self, body: str, limit: int) -> list[WebSearchHit]:
        lines = body.splitlines()
        hits: list[WebSearchHit] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            match = _LINK.search(line)
            if not match:
                continue
            title = _clean_markdown(match.group(1))
            url = decode_bing_redirect(match.group(2))
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            if url in seen or _is_noise(url, title):
                continue
            snippet = ""
            for following in lines[index + 1 : index + 3]:
                text = " ".join(following.split()).strip()
                if not text:
                    continue
                if _LINK.search(text):
                    break
                if len(text) > 30:
                    snippet = _clean_markdown(text)[:300]
                    break
            seen.add(url)
            hits.append(WebSearchHit(url=url, title=title or url, snippet=snippet))
            if len(hits) >= limit:
                break
        return hits

    async def probe(self) -> dict:
        """Live capability probe: one real query, bounded and evidence-labelled."""
        result = await self.search("deepseek harness agent")
        if result.error:
            return {
                "provider": self.provider_name,
                "available": False,
                "evidence_type": "real",
                "error": result.error,
            }
        return {
            "provider": self.provider_name,
            "available": True,
            "evidence_type": "real",
            "hit_count": len(result.hits),
        }

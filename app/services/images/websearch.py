from __future__ import annotations

import re

import httpx

from app.domain.models import WebImageCandidate

# Licenses safe for a WeChat public account article. Non-commercial (NC) and
# no-derivatives (ND) variants are deliberately excluded.
ALLOWED_LICENSE_TAGS = ("cc0", "cc by", "cc by-sa", "public domain", "pd ")


class WikimediaImageSearch:
    """Find freely licensed images on Wikimedia Commons without an API key.

    Every candidate carries attribution metadata (license, author, source page)
    so the article can credit the image honestly.
    """

    API_URL = "https://commons.wikimedia.org/w/api.php"

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 20.0):
        self._client = client
        self.timeout = timeout

    @staticmethod
    def _clean(value: str) -> str:
        value = re.sub(r"<[^>]+>", "", value or "")
        return " ".join(value.split()).strip()

    @staticmethod
    def _license_allowed(name: str) -> bool:
        lowered = (name or "").lower()
        if "-nc" in lowered or "-nd" in lowered:
            return False
        return any(tag in lowered for tag in ALLOWED_LICENSE_TAGS)

    async def search(self, query: str, limit: int = 4) -> list[WebImageCandidate]:
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": "1280",
            "format": "json",
            "origin": "*",
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": "wechat-ops-agent/0.1 image-search"},
        )
        try:
            response = await client.get(self.API_URL, params=params)
            response.raise_for_status()
        finally:
            if owns_client:
                await client.aclose()
        payload = response.json()
        pages = (payload.get("query") or {}).get("pages") or {}
        candidates: list[WebImageCandidate] = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                continue
            metadata = info.get("extmetadata") or {}
            license_name = self._clean(metadata.get("LicenseShortName", {}).get("value", ""))
            if not self._license_allowed(license_name):
                continue
            if (info.get("width") or 0) < 640:
                continue
            candidates.append(
                WebImageCandidate(
                    title=self._clean(page.get("title", "")),
                    thumb_url=info.get("thumburl") or info.get("url", ""),
                    original_url=info.get("url", ""),
                    license_name=license_name,
                    author=self._clean(metadata.get("Artist", {}).get("value", "")) or None,
                    source_page=info.get("descriptionurl", "https://commons.wikimedia.org"),
                    width=info.get("width"),
                    height=info.get("height"),
                )
            )
        return candidates[:limit]

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.domain.models import SourceSnapshot


@dataclass(frozen=True, slots=True)
class SafeFetchResult:
    url: str
    body: bytes
    content_type: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        else:
            self.text_parts.append(cleaned)


class SafeSourceFetcher:
    injection_patterns = {
        "ignore_previous_instructions": re.compile(
            r"(?i)ignore\s+(all\s+)?previous\s+instructions|忽略(以上|前文|之前)指令"
        ),
        "credential_exfiltration": re.compile(
            r"(?i)reveal|leak|print|return|泄露|输出|显示"
            r".{0,30}(api[_ -]?key|secret|token|password|密钥|令牌)"
        ),
        "tool_execution": re.compile(
            r"(?i)execute\s+(this\s+)?command|run\s+(this\s+)?command|执行.{0,12}命令"
        ),
    }

    def __init__(
        self,
        *,
        max_bytes: int = 1_000_000,
        max_excerpt_chars: int = 20_000,
        client: httpx.AsyncClient | None = None,
    ):
        self.max_bytes = max_bytes
        self.max_excerpt_chars = max_excerpt_chars
        self._client = client

    @staticmethod
    def _is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
            or address.is_multicast
        )

    @classmethod
    def _validate_host(cls, host: str) -> None:
        host = (host or "").lower()
        if not host:
            raise ValueError("source URL requires a host")
        if host in {"localhost", "localhost.localdomain"}:
            raise ValueError("private source hosts are not allowed")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and cls._is_blocked_address(literal):
            raise ValueError("private source hosts are not allowed")
        # Guard against DNS rebinding: a hostname that currently resolves to a
        # private/loopback address is treated as private even though the URL
        # string itself contains a normal-looking host. Resolution failures are
        # allowed through here; the fetch itself will surface connectivity.
        try:
            addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return
        for entry in addresses:
            try:
                address = ipaddress.ip_address(entry[4][0])
            except ValueError:
                continue
            if cls._is_blocked_address(address):
                raise ValueError("private source hosts are not allowed")

    @classmethod
    def _validate_url(cls, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("source URL must use http or https")
        cls._validate_host(parsed.hostname or "")

    async def fetch(self, url: str) -> SourceSnapshot:
        result = await self.fetch_bytes(url, max_bytes=self.max_bytes)
        body = result.body
        content_type = result.content_type
        text = body.decode("utf-8", errors="replace")
        title = urlparse(url).netloc
        if "html" in content_type.lower():
            parser = _TextExtractor()
            parser.feed(text)
            text = "\n".join(parser.text_parts)
            title = " ".join(parser.title_parts) or title
        excerpt = text[: self.max_excerpt_chars]
        flags = [
            name for name, pattern in self.injection_patterns.items() if pattern.search(excerpt)
        ]
        return SourceSnapshot(
            url=result.url,
            title=title,
            content_excerpt=excerpt,
            retrieved_at=datetime.now().astimezone(),
            content_hash=hashlib.sha256(body).hexdigest(),
            content_type=content_type,
            prompt_injection_flags=flags,
        )

    async def fetch_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        allowed_content_types: set[str] | None = None,
        max_redirects: int = 5,
    ) -> SafeFetchResult:
        """Fetch bounded bytes while validating every redirect before following it."""
        self._validate_url(url)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
            headers={"User-Agent": "wechat-ops-agent/0.1 source-snapshot"},
        )
        current_url = url
        try:
            for redirect_count in range(max_redirects + 1):
                self._validate_url(current_url)
                async with client.stream(
                    "GET", current_url, follow_redirects=False
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("source redirect is missing Location")
                        if redirect_count >= max_redirects:
                            raise ValueError("source exceeded redirect limit")
                        next_url = urljoin(str(response.url), location)
                        self._validate_url(next_url)
                        current_url = next_url
                        continue
                    response.raise_for_status()
                    self._validate_host(response.url.host or "")
                    content_type = response.headers.get(
                        "content-type", "application/octet-stream"
                    ).split(";", 1)[0].strip().lower()
                    if (
                        allowed_content_types is not None
                        and content_type not in allowed_content_types
                    ):
                        raise ValueError(f"unexpected content type {content_type}")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError(f"source exceeds {max_bytes} bytes")
                        chunks.append(chunk)
                    return SafeFetchResult(
                        url=str(response.url),
                        body=b"".join(chunks),
                        content_type=content_type,
                    )
        finally:
            if owns_client:
                await client.aclose()
        raise RuntimeError("safe source fetch ended without a response")

from __future__ import annotations

import re

import httpx
import pytest
import respx

from app.config.settings import Settings
from app.domain.models import WebSearchHit
from app.services.websearch.search import WebSearchService, decode_bing_redirect


def settings() -> Settings:
    return Settings(_env_file=None, web_search_provider="jina_bing")


def bing_markdown() -> str:
    return """Title: search result - Bing

URL Source: http://www.bing.com/search?q=test

Markdown Content:
About 123 results

1.   ## [**DeepSeek Harness** developer preview](https://www.bing.com/ck/a?!&&p=abc&u=aHR0cHM6Ly93d3cuZGVlcHNlZWsuY29tL2hhcm5lc3MvZW4v)

2 days ago· DeepSeek Harness is now available in developer preview to
developers building agent harnesses.

2.   ## [**Second result**](https://example.com/page)

Snippet line for the second result.

3.   ## [**Duplicate**](https://example.com/page)

Another snippet.
"""


def test_decode_bing_redirect_extracts_real_destination():
    raw = "https://www.bing.com/ck/a?!&&p=abc&u=aHR0cHM6Ly93d3cuZGVlcHNlZWsuY29tL2hhcm5lc3MvZW4v"

    decoded = decode_bing_redirect(raw)

    assert decoded == "https://www.deepseek.com/harness/en/"


def test_decode_bing_redirect_extracts_prefixed_destination():
    raw = "https://www.bing.com/ck/a?u=a1aHR0cHM6Ly93d3cuZGVlcHNlZWsuY29tLw"

    decoded = decode_bing_redirect(raw)

    assert decoded == "https://www.deepseek.com/"


def test_decode_bing_redirect_leaves_plain_urls_alone():
    assert decode_bing_redirect("https://example.com/page") == "https://example.com/page"


@respx.mock
@pytest.mark.asyncio
async def test_websearch_parses_hits_decodes_redirects_and_dedupes():
    respx.get(re.compile(r"https://r\.jina\.ai/.*")).mock(
        return_value=httpx.Response(200, text=bing_markdown())
    )
    service = WebSearchService(settings())

    result = await service.search("deepseek harness")

    assert result.error is None
    assert [str(hit.url) for hit in result.hits] == [
        "https://www.deepseek.com/harness/en/",
        "https://example.com/page",
    ]
    assert result.hits[0].title == "DeepSeek Harness developer preview"
    assert "developer preview" in result.hits[0].snippet
    assert all(isinstance(hit, WebSearchHit) for hit in result.hits)


@respx.mock
@pytest.mark.asyncio
async def test_websearch_network_error_is_recorded_not_raised():
    respx.get(re.compile(r"https://r\.jina\.ai/.*")).mock(
        return_value=httpx.Response(503, text="gateway down")
    )
    service = WebSearchService(settings())

    result = await service.search("anything")

    assert result.hits == []
    assert result.error is not None

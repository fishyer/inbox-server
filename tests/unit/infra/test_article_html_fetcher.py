"""直接 HTTP HTML 抓取适配器测试。"""

from __future__ import annotations

import httpx
import pytest

from inboxserver.infrastructure.article_archive.fetcher import DirectHtmlFetcher, HtmlFetchError


def _client(response: httpx.Response) -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"]
        return response

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_direct_fetch_accepts_html_and_redirects() -> None:
    async with _client(
        httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="<html>" + "x" * 100 + "</html>")
    ) as client:
        html = await DirectHtmlFetcher(client).fetch("https://example.com/a")

    assert html.startswith("<html>")


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(503, text="busy"), "http_status"),
        (
            httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"pdf"),
            "unsupported_content_type",
        ),
        (
            httpx.Response(200, headers={"content-type": "text/html"}, text="short"),
            "empty_html",
        ),
    ],
)
async def test_direct_fetch_rejects_invalid_responses(response, reason) -> None:
    async with _client(response) as client:
        with pytest.raises(HtmlFetchError, match=reason):
            await DirectHtmlFetcher(client).fetch("https://example.com/a")


async def test_direct_fetch_rejects_oversized_body() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"x" * 101,
    )
    async with _client(response) as client:
        with pytest.raises(HtmlFetchError, match="html_too_large"):
            await DirectHtmlFetcher(client, max_html_bytes=100).fetch("https://example.com/a")

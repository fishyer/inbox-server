"""文章归档直接 HTTP HTML 抓取适配器。"""

from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
)


class HtmlFetchError(RuntimeError):
    """直接抓取失败；仅暴露稳定错误码。"""


class DirectHtmlFetcher:
    """复用 worker 的 AsyncClient 抓取受限 HTML。"""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        timeout_seconds: float = 30,
        max_html_bytes: int = 8_000_000,
    ) -> None:
        self._http = http
        self._timeout_seconds = timeout_seconds
        self._max_html_bytes = max_html_bytes

    async def fetch(self, url: str) -> str:
        """跟随重定向抓取 HTML，并限制类型、状态、大小和空正文。"""
        try:
            response = await self._http.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                follow_redirects=True,
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise HtmlFetchError("request_failed") from error
        if not 200 <= response.status_code < 300:
            raise HtmlFetchError("http_status")
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise HtmlFetchError("unsupported_content_type")
        content = response.content
        if len(content) > self._max_html_bytes:
            raise HtmlFetchError("html_too_large")
        html = response.text
        if len(html.strip()) < 100:
            raise HtmlFetchError("empty_html")
        return html

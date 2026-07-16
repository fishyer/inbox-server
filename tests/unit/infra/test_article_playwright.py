"""文章归档 headed Playwright HTML 兜底测试。"""

from __future__ import annotations

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from inboxserver.infrastructure.browser.playwright_runtime import (
    RenderedHtmlError,
    fetch_rendered_html,
)


class _Page:
    def __init__(self, html: str, goto_error: Exception | None = None):
        self._html = html
        self._goto_error = goto_error
        self.goto_args = None

    async def goto(self, url, **kwargs):
        self.goto_args = (url, kwargs)
        if self._goto_error:
            raise self._goto_error

    async def wait_for_selector(self, selector, **kwargs):
        assert selector == "#js_content"

    async def wait_for_load_state(self, state, **kwargs):
        assert state == "networkidle"

    async def evaluate(self, script):
        assert "scrollTo" in script

    async def wait_for_timeout(self, milliseconds):
        assert milliseconds == 1000

    async def content(self):
        return self._html


class _Context:
    def __init__(self, page: _Page):
        self.page = page
        self.closed = False

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class _Browser:
    def __init__(self, context: _Context):
        self.context = context
        self.user_agent = None

    async def new_context(self, **kwargs):
        self.user_agent = kwargs.get("user_agent")
        return self.context


async def test_fetch_rendered_html_returns_content_and_closes_context() -> None:
    page = _Page("<html>" + "正文" * 100 + "</html>")
    context = _Context(page)
    browser = _Browser(context)

    html = await fetch_rendered_html(
        "https://mp.weixin.qq.com/s/abc",
        timeout_seconds=45,
        max_html_bytes=1_000_000,
        browser=browser,
    )

    assert "正文" in html
    assert page.goto_args[1]["wait_until"] == "domcontentloaded"
    assert page.goto_args[1]["timeout"] == 45_000
    assert browser.user_agent
    assert context.closed is True


async def test_fetch_rendered_html_closes_context_on_navigation_timeout() -> None:
    page = _Page("", goto_error=PlaywrightTimeoutError("timeout"))
    context = _Context(page)

    with pytest.raises(RenderedHtmlError, match="navigation_failed"):
        await fetch_rendered_html(
            "https://example.com/a",
            timeout_seconds=1,
            max_html_bytes=100,
            browser=_Browser(context),
        )

    assert context.closed is True


async def test_fetch_rendered_html_rejects_oversized_content() -> None:
    context = _Context(_Page("x" * 101))

    with pytest.raises(RenderedHtmlError, match="html_too_large"):
        await fetch_rendered_html(
            "https://example.com/a",
            timeout_seconds=1,
            max_html_bytes=100,
            browser=_Browser(context),
        )

    assert context.closed is True

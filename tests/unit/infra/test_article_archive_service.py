"""文章归档应用编排分支测试。"""

from __future__ import annotations

from datetime import UTC, datetime

from inboxserver.domain.policy.article_archive import DefuddleArticle
from inboxserver.infrastructure.article_archive.service import ArticleArchiveService
from inboxserver.plugins.contracts import DispatchOutcome


class _Fetcher:
    def __init__(self, html: str = "direct", error: Exception | None = None):
        self.html = html
        self.error = error
        self.calls = 0

    async def fetch(self, url: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return self.html


class _Bridge:
    def __init__(self, articles: list[DefuddleArticle]):
        self.articles = list(articles)
        self.parsed: list[str] = []
        self.rendered = []

    async def parse(self, url: str, html: str) -> DefuddleArticle:
        self.parsed.append(html)
        return self.articles.pop(0)

    async def render(self, metadata: dict, markdown: str) -> str:
        self.rendered.append((metadata, markdown))
        return f"---\ntitle: {metadata['title']}\n---\n{markdown}\n"


class _BrowserFetch:
    def __init__(self, html: str = "rendered", error: Exception | None = None):
        self.html = html
        self.error = error
        self.calls = 0

    async def __call__(self, url: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return self.html


class _WebDav:
    def __init__(self, exists: bool = False, error: Exception | None = None):
        self._exists = exists
        self.error = error
        self.checked: list[str] = []
        self.uploaded: list[tuple[str, bytes]] = []

    async def exists(self, remote_path: str) -> bool:
        self.checked.append(remote_path)
        if self.error:
            raise self.error
        return self._exists

    async def upload_bytes(self, remote_path: str, content: bytes) -> None:
        if self.error:
            raise self.error
        self.uploaded.append((remote_path, content))


def _service(fetcher, bridge, browser, webdav) -> ArticleArchiveService:
    return ArticleArchiveService(
        fetcher=fetcher,
        bridge=bridge,
        browser_fetch=browser,
        webdav=webdav,
        remote_dir="/我的坚果云/文章归档",
        min_visible_characters=20,
        clock=lambda: datetime(2026, 7, 16, 1, tzinfo=UTC),
    )


def _valid(title: str = "测试 文章") -> DefuddleArticle:
    return DefuddleArticle(
        title=title,
        author="作者",
        published_at="2026-07-15",
        markdown="有效正文" * 20 + "\n![图](https://img.example.com/a.jpg)",
    )


async def test_direct_valid_article_skips_browser_and_uploads_markdown() -> None:
    fetcher = _Fetcher()
    bridge = _Bridge([_valid()])
    browser = _BrowserFetch()
    webdav = _WebDav()
    service = _service(fetcher, bridge, browser, webdav)

    ok, outcome = await service.process(
        {"url": "https://example.com/a", "title": "queue title", "tags": ["AI"]}
    )

    assert ok is True and outcome is DispatchOutcome.OK
    assert browser.calls == 0
    assert webdav.uploaded[0][0] == "/我的坚果云/文章归档/20260716-测试文章.md"
    assert "https://img.example.com/a.jpg" in webdav.uploaded[0][1].decode()
    assert bridge.rendered[0][0]["tags"] == ["AI"]


async def test_short_direct_result_uses_playwright_then_uploads() -> None:
    bridge = _Bridge([DefuddleArticle(title="短", markdown="短"), _valid("完整文章")])
    browser = _BrowserFetch()
    webdav = _WebDav()

    ok, outcome = await _service(_Fetcher(), bridge, browser, webdav).process(
        {"url": "https://example.com/a", "tags": []}
    )

    assert ok is True and outcome is DispatchOutcome.OK
    assert bridge.parsed == ["direct", "rendered"]
    assert browser.calls == 1
    assert len(webdav.uploaded) == 1


async def test_preexcluded_and_twice_invalid_pages_are_successful_skips() -> None:
    pre_fetcher = _Fetcher()
    pre_bridge = _Bridge([])
    pre_browser = _BrowserFetch()
    pre_webdav = _WebDav()
    assert await _service(pre_fetcher, pre_bridge, pre_browser, pre_webdav).process(
        {"url": "https://youtube.com/watch?v=1"}
    ) == (True, DispatchOutcome.OK)
    assert pre_fetcher.calls == 0 and pre_browser.calls == 0

    bridge = _Bridge(
        [
            DefuddleArticle(title="短", markdown="短"),
            DefuddleArticle(title="还是短", markdown="还是短"),
        ]
    )
    webdav = _WebDav()
    assert await _service(_Fetcher(), bridge, _BrowserFetch(), webdav).process(
        {"url": "https://example.com/navigation"}
    ) == (True, DispatchOutcome.OK)
    assert not webdav.checked and not webdav.uploaded


async def test_existing_target_is_successful_skip_without_overwrite() -> None:
    webdav = _WebDav(exists=True)

    result = await _service(_Fetcher(), _Bridge([_valid()]), _BrowserFetch(), webdav).process(
        {"url": "https://example.com/a", "tags": []}
    )

    assert result == (True, DispatchOutcome.OK)
    assert not webdav.uploaded


async def test_recoverable_browser_or_webdav_failures_return_fail() -> None:
    short = DefuddleArticle(title="短", markdown="短")
    browser_failure = await _service(
        _Fetcher(),
        _Bridge([short]),
        _BrowserFetch(error=RuntimeError("timeout")),
        _WebDav(),
    ).process({"url": "https://example.com/a"})
    assert browser_failure == (False, DispatchOutcome.FAIL)

    webdav_failure = await _service(
        _Fetcher(),
        _Bridge([_valid()]),
        _BrowserFetch(),
        _WebDav(error=RuntimeError("temporary")),
    ).process({"url": "https://example.com/a"})
    assert webdav_failure == (False, DispatchOutcome.FAIL)

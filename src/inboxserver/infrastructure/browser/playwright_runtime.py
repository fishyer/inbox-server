"""playwright 运行时：进程级单例 playwright + chromium browser（强制 headed）。

FastAPI lifespan 启动时 get_browser()，应用退出时 shutdown()。
强制 headed（headless=False 硬编码）：知乎等平台检测 headless 反爬，绝不用 headless。
容器部署需 xvfb-run 提供 X display（headed 要显示环境）。

Item 66（@asynccontextmanager）：browser_session() 统一 lifecycle，确保配对调用。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from playwright.async_api import (
    Browser,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from inboxserver.infrastructure.article_archive.fetcher import USER_AGENT

_pw: Playwright | None = None
_browser: Browser | None = None


class RenderedHtmlError(RuntimeError):
    """渲染后 HTML 获取失败；仅暴露稳定错误码。"""


async def get_browser() -> Browser:
    """单例 chromium（强制 headed）。

    headless=False 硬编码：知乎等平台检测 headless 反爬，任何场景都不用 headless。
    容器部署需 xvfb-run 提供 X display。
    --no-sandbox 适配容器权限；--disable-dev-shm-usage 防 /dev/shm 满溢。
    """
    global _pw, _browser
    if _browser is None:
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
    return _browser


async def fetch_rendered_html(
    url: str,
    *,
    timeout_seconds: float,
    max_html_bytes: int,
    browser: Browser | None = None,
) -> str:
    """用现有 headed browser 获取渲染后 HTML，并释放独立 context。"""
    runtime = browser or await get_browser()
    context = await runtime.new_context(user_agent=USER_AGENT)
    try:
        page = await context.new_page()
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(timeout_seconds * 1000),
            )
        except PlaywrightError as error:
            raise RenderedHtmlError("navigation_failed") from error
        with suppress(PlaywrightTimeoutError):
            await page.wait_for_selector("#js_content", state="attached", timeout=15_000)
        with suppress(PlaywrightTimeoutError):
            await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
        html = await page.content()
        if len(html.encode()) > max_html_bytes:
            raise RenderedHtmlError("html_too_large")
        if len(html.strip()) < 100:
            raise RenderedHtmlError("empty_html")
        return html
    finally:
        await context.close()


@asynccontextmanager
async def browser_session() -> AsyncIterator[Browser]:
    """@asynccontextmanager 封装 browser lifecycle（Item 66）。

    用法：async with browser_session() as browser: ...
    确保 get_browser / shutdown 配对（退出时自动清理）。
    """
    browser = await get_browser()
    try:
        yield browser
    finally:
        await shutdown()


async def shutdown() -> None:
    """关闭 browser + playwright（应用退出 / 测试清理时调用）。"""
    global _pw, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _pw is not None:
        await _pw.stop()
        _pw = None

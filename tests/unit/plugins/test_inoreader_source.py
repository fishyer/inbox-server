"""inoreader source 单测：mock session_manager/pool/page(DOM evaluate) → 解析 → 增量入队。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from inboxserver.plugins.sources.inoreader import InoreaderSource


@pytest.fixture
def source():
    return InoreaderSource(
        {"credential_name": "ino_creds"},
        session_manager=AsyncMock(),
        pool=AsyncMock(),
        queue_repo=AsyncMock(),
        http=AsyncMock(),
        llm_api_key="key",
        baseline_repo=AsyncMock(),
    )


async def test_collect_extracts_articles_and_enqueues(source):
    """goto /starred → DOM evaluate 提取文章 → 增量 → 入队 link。"""
    source._session.acquire.return_value = {"cookies": []}
    page = AsyncMock()
    page.url = "https://www.inoreader.com/starred"
    page.evaluate.return_value = [
        {"url": "https://blog.example.com/a", "title": "A", "key": "article_1"},
        {"url": "https://blog.example.com/b", "title": "B", "key": "article_2"},
    ]
    source._pool.context_for.return_value = AsyncMock(new_page=AsyncMock(return_value=page))
    source._baseline.get_known.return_value = set()
    source._http.post.return_value.json.return_value = {"choices": [{"message": {"content": "tag1,tag2"}}]}

    result = await source.collect()

    assert result.enqueued == {"link": 2}
    assert source._queue.enqueue.await_count == 2
    source._baseline.save_known.assert_called_once()


async def test_collect_skips_known(source):
    """已知 article key 跳过。"""
    source._session.acquire.return_value = {"cookies": []}
    page = AsyncMock()
    page.url = "https://www.inoreader.com/starred"
    page.evaluate.return_value = [{"url": "https://x.com/a", "title": "A", "key": "article_1"}]
    source._pool.context_for.return_value = AsyncMock(new_page=AsyncMock(return_value=page))
    source._baseline.get_known.return_value = {"article_1"}

    result = await source.collect()

    assert result.enqueued == {}
    assert result.skipped == 1
    source._queue.enqueue.assert_not_called()


async def test_collect_not_logged_in_marks_expired(source):
    """重定向 /login → mark_expired + 错误返回。"""
    source._session.acquire.return_value = {"cookies": []}
    page = AsyncMock()
    page.url = "https://www.inoreader.com/login"
    source._pool.context_for.return_value = AsyncMock(new_page=AsyncMock(return_value=page))

    result = await source.collect()

    assert "error" in (result.meta or {})
    source._session.mark_expired.assert_called_once_with("inoreader")

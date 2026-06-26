"""youtube source 单测：mock session/pool/page(DOM) → video_id → 增量入队 link。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from inboxserver.plugins.sources.youtube import YouTubeSource


@pytest.fixture
def source():
    return YouTubeSource(
        {"credential_name": "yt_creds"},
        session_manager=AsyncMock(),
        pool=AsyncMock(),
        queue_repo=AsyncMock(),
        http=AsyncMock(),
        llm_api_key="k",
        baseline_repo=AsyncMock(),
    )


async def test_collect_extracts_videos_and_enqueues(source):
    source._session.acquire.return_value = {"cookies": []}
    page = AsyncMock()
    page.url = "https://www.youtube.com/playlist?list=WL"
    page.evaluate.return_value = [
        {"id": "vid1", "title": "V1"},
        {"id": "vid2", "title": "V2"},
    ]
    source._pool.context_for.return_value = AsyncMock(new_page=AsyncMock(return_value=page))
    source._baseline.get_known.return_value = set()
    source._http.post.return_value.json.return_value = {"choices": [{"message": {"content": "t1,t2"}}]}

    result = await source.collect()

    assert result.enqueued == {"link": 2}
    payload = source._queue.enqueue.await_args_list[0].args[1]
    assert payload["url"] == "https://www.youtube.com/watch?v=vid1"


async def test_collect_skips_known(source):
    source._session.acquire.return_value = {"cookies": []}
    page = AsyncMock()
    page.url = "https://www.youtube.com/playlist?list=WL"
    page.evaluate.return_value = [{"id": "vid1", "title": "V1"}]
    source._pool.context_for.return_value = AsyncMock(new_page=AsyncMock(return_value=page))
    source._baseline.get_known.return_value = {"vid1"}

    result = await source.collect()

    assert result.enqueued == {}
    assert result.skipped == 1
    source._queue.enqueue.assert_not_called()


async def test_collect_not_logged_in_marks_expired(source):
    source._session.acquire.return_value = {"cookies": []}
    page = AsyncMock()
    page.url = "https://accounts.google.com/signin"
    source._pool.context_for.return_value = AsyncMock(new_page=AsyncMock(return_value=page))

    result = await source.collect()

    assert "error" in (result.meta or {})
    source._session.mark_expired.assert_called_once_with("youtube")

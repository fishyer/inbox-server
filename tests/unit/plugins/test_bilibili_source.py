"""bilibili source 单测：mock session/scraper(fetch) → parse 收藏 API → 增量入队。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from inboxserver.plugins.sources.bilibili import parse_bilibili_favorites


def test_parse_bilibili_favorites():
    body = json.dumps(
        {"data": {"medias": [{"bvid": "BV1xx", "title": "视频A"}, {"bvid": "BV2yy", "title": "B"}]}}
    )
    items = parse_bilibili_favorites(body)
    assert len(items) == 2
    assert items[0].url == "https://www.bilibili.com/video/BV1xx"
    assert items[0].title == "视频A"


def test_parse_invalid_json():
    assert parse_bilibili_favorites("not json") == []
    assert parse_bilibili_favorites('{"data":{}}') == []


@pytest.fixture
def source():
    return type(
        "S",
        (),
        {
            "_credential_name": "bili_creds",
            "_media_id": "123",
            "_session": AsyncMock(),
            "_scraper": AsyncMock(),
            "_queue": AsyncMock(),
            "_http": AsyncMock(),
            "_llm_key": "k",
            "_baseline": AsyncMock(),
        },
    )()


async def test_collect_via_scraper_and_dedup(source):
    from inboxserver.plugins.sources.bilibili import BilibiliSource

    real = BilibiliSource(
        {"credential_name": "bili_creds", "media_id": "123"},
        session_manager=AsyncMock(),
        scraper=AsyncMock(),
        queue_repo=AsyncMock(),
        http=AsyncMock(),
        llm_api_key="k",
        baseline_repo=AsyncMock(),
    )
    real._session.acquire.return_value = {"cookies": []}
    real._scraper.fetch_via_page.return_value = {
        "status": 200,
        "body": json.dumps({"data": {"medias": [{"bvid": "BV1", "title": "X"}]}}),
    }
    real._baseline.get_known.return_value = set()
    real._http.post.return_value.json.return_value = {"choices": [{"message": {"content": "t1,t2"}}]}

    result = await real.collect()

    assert result.enqueued == {"link": 1}
    real._scraper.fetch_via_page.assert_called_once()
    real._queue.enqueue.assert_called_once()
    payload = real._queue.enqueue.await_args.args[1]
    assert payload["url"] == "https://www.bilibili.com/video/BV1"

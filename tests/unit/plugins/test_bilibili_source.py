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
    # 翻页：第 1 页 1 条新，第 2 页空 → 停止翻页
    real._scraper.fetch_via_page.side_effect = [
        {"status": 200, "body": json.dumps({"data": {"medias": [{"bvid": "BV1", "title": "X"}]}})},
        {"status": 200, "body": json.dumps({"data": {"medias": []}})},  # 空页 → 停止翻页
    ]
    real._baseline.get_known.return_value = set()
    real._http.post.return_value.json.return_value = {"choices": [{"message": {"content": "t1,t2"}}]}

    result = await real.collect()

    assert result.enqueued == {"link": 1}
    assert real._scraper.fetch_via_page.await_count == 2  # 翻 2 页（第 2 空页停）
    real._queue.enqueue.assert_called_once()
    payload = real._queue.enqueue.await_args.args[1]
    assert payload["url"] == "https://www.bilibili.com/video/BV1"


async def test_collect_paginate_breaks_on_all_known():
    """增量：翻到整页全 known（baseline 已有）即停——新收藏在前，旧页全是已知。"""
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
    # baseline 已有旧收藏 BV_old → 第 2 页整页全 known 触发 break
    real._baseline.get_known.return_value = {"https://www.bilibili.com/video/BV_old"}
    real._scraper.fetch_via_page.side_effect = [
        {"status": 200, "body": json.dumps({"data": {"medias": [
            {"bvid": "BV_new", "title": "新视频"},
            {"bvid": "BV_old", "title": "旧视频"},
        ]}})},
        {"status": 200, "body": json.dumps({"data": {"medias": [
            {"bvid": "BV_old", "title": "旧视频"},  # 整页全 known → 停止翻页
        ]}})},
    ]
    real._http.post.return_value.json.return_value = {"choices": [{"message": {"content": "t"}}]}

    result = await real.collect()

    assert result.enqueued == {"link": 1}  # 只 BV_new（增量，旧的不入队）
    assert real._scraper.fetch_via_page.await_count == 2  # 翻 2 页停（第 3 不调）

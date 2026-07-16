"""文章归档队列复用通用重试、去重与 DLQ 的集成测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from inboxserver.domain.models import ItemKind, QueueLimits
from inboxserver.domain.policy.dedup import fingerprint
from inboxserver.infrastructure.queue.dedup_store import DedupStore
from inboxserver.infrastructure.queue.rate_guard import RateGuard
from inboxserver.infrastructure.queue.repository import RedisQueueRepository, queue_key
from inboxserver.plugins.contracts import DispatchOutcome
from inboxserver.workers.consumer import consume

LIMITS = QueueLimits(window_count=100, window_sec=60, daily_limit=100, interval=0.01)


async def _run(fake_redis, process_fn, *, settle: float) -> RedisQueueRepository:
    repo = RedisQueueRepository(fake_redis)
    await repo.enqueue(ItemKind.ARTICLE, {"url": "https://example.com/a", "title": "A"})
    stop = asyncio.Event()
    task = asyncio.create_task(
        consume(
            ItemKind.ARTICLE,
            repo,
            DedupStore(fake_redis),
            RateGuard(fake_redis),
            process_fn,
            "article",
            limits=LIMITS,
            stop_event=stop,
        )
    )
    await asyncio.sleep(settle)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    return repo


async def test_article_archive_success_marks_url_hash_done(fake_redis) -> None:
    repo = await _run(
        fake_redis,
        AsyncMock(return_value=(True, DispatchOutcome.OK)),
        settle=0.1,
    )

    fp = fingerprint({"url": "https://example.com/a"}, ItemKind.ARTICLE)
    assert await DedupStore(fake_redis).is_done(queue_key(ItemKind.ARTICLE), fp)
    assert await repo.dlq_len(ItemKind.ARTICLE) == 0


async def test_article_archive_failure_retries_then_enters_own_dlq(fake_redis) -> None:
    repo = await _run(
        fake_redis,
        AsyncMock(return_value=(False, DispatchOutcome.FAIL)),
        settle=0.5,
    )

    assert await repo.dlq_len(ItemKind.ARTICLE) == 1
    item = (await repo.peek_dlq(ItemKind.ARTICLE))[0]
    assert item["url"] == "https://example.com/a"
    assert item["title"] == "A"
    assert item["retry"] == 3

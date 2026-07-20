"""worker 容器健康探针的纯逻辑测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from inboxserver.workers.healthcheck import heartbeat_is_fresh


def test_heartbeat_is_fresh_accepts_recent_utc_value() -> None:
    now = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)

    assert heartbeat_is_fresh(
        b"2026-07-20T12:59:30+00:00",
        now=now,
    )


def test_heartbeat_is_fresh_rejects_missing_stale_or_invalid_value() -> None:
    now = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)

    assert not heartbeat_is_fresh(None, now=now)
    assert not heartbeat_is_fresh("invalid", now=now)
    assert not heartbeat_is_fresh(
        (now - timedelta(seconds=91)).isoformat(),
        now=now,
    )


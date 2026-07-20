"""worker 容器健康探针：以 Redis TTL 心跳判断事件循环是否仍在推进。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from redis import Redis

from inboxserver.config.settings import settings
from inboxserver.infrastructure.operations.heartbeat import (
    WORKER_HEARTBEAT_KEY,
    WORKER_HEARTBEAT_TTL_SECONDS,
)


def heartbeat_is_fresh(
    value: bytes | str | None,
    *,
    now: datetime | None = None,
) -> bool:
    """仅接受 TTL 窗口内的 UTC 心跳，拒绝缺失、损坏和未来时间。"""
    if value is None:
        return False
    raw = value.decode() if isinstance(value, bytes) else value
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if moment.tzinfo is None:
        return False
    current = now or datetime.now(UTC)
    age = current.astimezone(UTC) - moment.astimezone(UTC)
    return timedelta(0) <= age <= timedelta(seconds=WORKER_HEARTBEAT_TTL_SECONDS)


def probe_worker_heartbeat(redis_url: str) -> bool:
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=3,
        socket_timeout=3,
        health_check_interval=30,
    )
    try:
        return heartbeat_is_fresh(client.get(WORKER_HEARTBEAT_KEY))
    except Exception:
        return False
    finally:
        client.close()


def main() -> None:
    raise SystemExit(0 if probe_worker_heartbeat(settings.redis_url) else 1)


if __name__ == "__main__":
    main()

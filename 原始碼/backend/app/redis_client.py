"""Redis 连接（任务队列 + 并发闸 + 进度通道）。"""
from __future__ import annotations

import redis

from .config import get_settings

_settings = get_settings()

# decode_responses=True：键值用 str，便于队列/进度处理。
client: redis.Redis = redis.from_url(_settings.redis_url, decode_responses=True)


def ping() -> bool:
    """健康检查：能否连通 Redis。"""
    try:
        return bool(client.ping())
    except Exception:
        return False

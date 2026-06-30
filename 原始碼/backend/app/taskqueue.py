"""Redis 任务队列 + 并发闸 + 进度通道 — Task 5 / 7。

并发规则(走配置):同时运行 running≤MAX_RUNNING(默认2)、等待 queued≤MAX_QUEUED(默认2);
系统内 running+queued 达到上限(默认4)时拒绝新请求。
状态机:queued → running → done/failed/canceled;状态以 PostgreSQL 为准,Redis 维护实时队列与进度。
进度通过 Redis pub/sub + 列表回放推给 SSE。
"""
from __future__ import annotations

import json
import threading
import time
import uuid

from .config import get_settings
from .db import SessionLocal
from .models import GenerationTask
from .redis_client import client

_settings = get_settings()

# ── Redis 键 ──
K_QUEUE = "bms:queue"               # list:排队中的 task_id(RPUSH 入队,LPOP 出队)
K_RUNNING = "bms:running"           # set:运行中的 task_id
K_MODE = "bms:task:{}:mode"         # str:该任务的生成模式
K_CANCEL = "bms:task:{}:cancel"     # str:取消标记
K_LOG = "bms:task:{}:events"        # list:事件回放(SSE 断线重连补拉)
CH_EVENTS = "bms:task:{}:channel"   # pub/sub 频道
_TTL = 3600                          # 进度/回放键过期秒数


class QueueFull(Exception):
    """系统排队已满(running+queued 达上限)。"""


def _capacity() -> int:
    return _settings.max_running + _settings.max_queued


def counts() -> tuple[int, int]:
    """返回 (running, queued)。"""
    return int(client.scard(K_RUNNING) or 0), int(client.llen(K_QUEUE) or 0)


def enqueue(task_id: str, mode: str = "free") -> int:
    """入队;若系统已满则抛 QueueFull。返回排队位置(1 开始)。"""
    running, queued = counts()
    if running + queued >= _capacity():
        raise QueueFull(
            f"排队已满(运行{running}/上限{_settings.max_running}，等待{queued}/上限{_settings.max_queued})，稍后再试"
        )
    client.set(K_MODE.format(task_id), mode, ex=_TTL * 24)
    client.rpush(K_QUEUE, task_id)
    return position(task_id)


def position(task_id: str) -> int | None:
    """排队位置(1 = 队首);不在队列返回 None。"""
    ids = client.lrange(K_QUEUE, 0, -1)
    for i, tid in enumerate(ids):
        if tid == task_id:
            return i + 1
    return None


def request_cancel(task_id: str) -> None:
    client.set(K_CANCEL.format(task_id), "1", ex=_TTL)
    # 若还在排队,直接移出队列
    client.lrem(K_QUEUE, 0, task_id)


def is_canceled(task_id: str) -> bool:
    return client.exists(K_CANCEL.format(task_id)) == 1


def publish(task_id: str, event: dict) -> None:
    """发布一条进度事件:写入回放列表 + pub/sub。"""
    payload = json.dumps(event, ensure_ascii=False)
    pipe = client.pipeline()
    pipe.rpush(K_LOG.format(task_id), payload)
    pipe.expire(K_LOG.format(task_id), _TTL)
    pipe.publish(CH_EVENTS.format(task_id), payload)
    pipe.execute()


def backlog(task_id: str) -> list[str]:
    """取已发布的事件(供 SSE 断线重连补拉)。"""
    return client.lrange(K_LOG.format(task_id), 0, -1)


def status() -> dict:
    """队列总体状态 — Task 12。"""
    running, queued = counts()
    return {
        "running": running,
        "queued": queued,
        "max_running": _settings.max_running,
        "max_queued": _settings.max_queued,
        "capacity": _capacity(),
        "running_ids": list(client.smembers(K_RUNNING)),
        "queued_ids": client.lrange(K_QUEUE, 0, -1),
    }


def _cleanup_task_keys(task_id: str) -> None:
    client.delete(K_MODE.format(task_id), K_CANCEL.format(task_id))


def process_task(task_id: str) -> None:
    """处理单个任务(worker 调用,也可在测试中直接调用)。"""
    from . import generation

    client.sadd(K_RUNNING, task_id)
    mode = client.get(K_MODE.format(task_id)) or "free"
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, uuid.UUID(task_id))
        if task is None:
            return
        if is_canceled(task_id):
            task.status = "canceled"
            db.commit()
            publish(task_id, {"type": "canceled", "msg": "已取消"})
            return

        def on_event(t: str, data: dict):
            publish(task_id, {"type": t, **data})

        generation.execute_task(
            db, task, mode=mode, on_event=on_event, should_cancel=lambda: is_canceled(task_id)
        )
    except Exception as e:  # noqa: BLE001 已在 execute_task 内落库 failed
        publish(task_id, {"type": "error", "msg": str(e)})
    finally:
        client.srem(K_RUNNING, task_id)
        _cleanup_task_keys(task_id)
        db.close()


# ── 后台调度线程 ──
class Dispatcher:
    """从 Redis 队列取任务,在不超过 MAX_RUNNING 的前提下并发处理。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import os

        if os.environ.get("BMS_NO_DISPATCHER") == "1":
            return  # 测试环境:不自动起后台调度,改由测试直接调用 process_task
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="bms-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                running, _ = counts()
                if running >= _settings.max_running:
                    time.sleep(0.3)
                    continue
                task_id = client.lpop(K_QUEUE)
                if not task_id:
                    time.sleep(0.3)
                    continue
                threading.Thread(
                    target=process_task, args=(task_id,), name=f"bms-worker-{task_id[:8]}", daemon=True
                ).start()
            except Exception:
                time.sleep(0.5)


dispatcher = Dispatcher()

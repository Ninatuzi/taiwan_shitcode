"""任务状态 / SSE 进度 / 取消 / 队列状态 — Task 5 / 7 / 12。"""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import taskqueue
from ..db import get_db
from ..models import GenerationResult, GenerationTask

router = APIRouter(prefix="/api", tags=["tasks"])

_TERMINAL = {"done", "failed", "canceled"}


@router.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    task = db.get(GenerationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    result = (
        db.query(GenerationResult).filter(GenerationResult.task_id == task_id).first()
        if task.status == "done"
        else None
    )
    return {
        "task_id": str(task.id),
        "case_id": str(task.case_id),
        "status": task.status,
        "queue_position": taskqueue.position(str(task.id)),
        "total_chapters": task.total_chapters,
        "current_chapter": task.current_chapter,
        "tc_count": result.tc_count if result else None,
        "error_msg": task.error_msg,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    task = db.get(GenerationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task 不存在")
    if task.status in _TERMINAL:
        return {"task_id": str(task_id), "status": task.status, "msg": "任务已结束,无需取消"}
    taskqueue.request_cancel(str(task_id))
    # 若还在排队,立即落库 canceled(running 中的由 worker 处理)
    if task.status == "queued":
        task.status = "canceled"
        db.commit()
    return {"task_id": str(task_id), "status": "canceling"}


@router.get("/queue/status")
def queue_status() -> dict:
    return taskqueue.status()


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: uuid.UUID, request: Request) -> StreamingResponse:
    """SSE 进度推送。事件类型:chunk/progress/log/done/error/canceled。

    采用回放列表轮询:连接后从头补发已产生的事件(断线重连可续),再实时跟进新事件。
    """
    tid = str(task_id)

    async def gen():
        idx = 0
        # 最长保持 ~10 分钟(LLM_TIMEOUT 量级);终止事件出现即结束
        for _ in range(3000):
            if await request.is_disconnected():
                return
            items = taskqueue.backlog(tid)
            if len(items) > idx:
                for raw in items[idx:]:
                    yield f"data: {raw}\n\n"
                    idx += 1
                    try:
                        if json.loads(raw).get("type") in _TERMINAL:
                            return
                    except Exception:
                        pass
            await asyncio.sleep(0.4)
        yield 'data: {"type":"log","msg":"stream timeout"}\n\n'

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

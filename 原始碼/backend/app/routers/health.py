"""健康检查 — Task 0。含 DB / Redis 连通状态。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import db as db_module
from .. import redis_client
from ..schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_ok = db_module.ping()
    redis_ok = redis_client.ping()
    status = "ok" if (db_ok and redis_ok) else "degraded"
    return HealthResponse(status=status, db=db_ok, redis=redis_ok)

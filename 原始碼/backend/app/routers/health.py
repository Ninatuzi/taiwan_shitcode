"""健康检查 — Task 0。含 DB / Redis 连通状态与当前生效的 LLM 配置。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import db as db_module
from .. import redis_client
from ..config import get_settings
from ..schemas import HealthResponse, LLMInfo

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_ok = db_module.ping()
    redis_ok = redis_client.ping()
    s = get_settings()
    status = "ok" if (db_ok and redis_ok) else "degraded"
    # 透出当前实际生效的模型端点/模型名/是否设了 key（不泄露 key 本身），
    # 方便确认运行中的服务到底连的哪个端点。
    return HealthResponse(
        status=status,
        db=db_ok,
        redis=redis_ok,
        llm=LLMInfo(
            base_url=s.llm_base_url,
            model=s.llm_model,
            api_key_set=bool(s.llm_api_key),
        ),
    )

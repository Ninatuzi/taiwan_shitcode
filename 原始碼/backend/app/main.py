"""FastAPI 应用入口 — 装配 Task 0~4 的路由与每日清理调度。

运行：
    cd 原始碼 && .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import SessionLocal
from .routers import admin, cases, health
from .storage import cleanup_expired

_settings = get_settings()
logger = logging.getLogger("bms")

_scheduler: BackgroundScheduler | None = None


def _run_cleanup_job() -> None:
    db = SessionLocal()
    try:
        result = cleanup_expired(db)
        logger.info("定时清理: %s", result)
    except Exception:
        logger.exception("定时清理失败")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_cleanup_job,
        "interval",
        hours=_settings.cleanup_interval_hours,
        id="cleanup_expired",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("清理调度已启动，周期 %sh", _settings.cleanup_interval_hours)
    try:
        yield
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)


app = FastAPI(title="BMS 测试用例生成平台 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(cases.router)
app.include_router(admin.router)

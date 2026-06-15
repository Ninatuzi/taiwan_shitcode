"""管理接口 — Task 4：手动触发过期清理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import storage
from ..db import get_db
from ..schemas import CleanupResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup(db: Session = Depends(get_db)) -> CleanupResponse:
    result = storage.cleanup_expired(db)
    return CleanupResponse(**result)

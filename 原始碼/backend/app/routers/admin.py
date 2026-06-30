"""管理接口 — Task 4 清理 + Task 11 嵌入重建。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..db import get_db
from ..embeddings import embed_text, html_to_text
from ..models import GenerationResult
from ..schemas import CleanupResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup(db: Session = Depends(get_db)) -> CleanupResponse:
    result = storage.cleanup_expired(db)
    return CleanupResponse(**result)


@router.post("/reindex")
def reindex(
    db: Session = Depends(get_db),
    force: bool = Query(False, description="True=重算全部;False=只补未建向量的"),
) -> dict:
    """为生成结果灌入嵌入向量(Task 11 语义检索前置)。嵌入模型不可用时计入 failed。"""
    stmt = select(GenerationResult)
    if not force:
        stmt = stmt.where(GenerationResult.embedding.is_(None))
    rows = db.execute(stmt).scalars().all()
    embedded = failed = 0
    for r in rows:
        vec = embed_text(html_to_text(r.html))
        if vec is None:
            failed += 1
            continue
        r.embedding = vec
        embedded += 1
    db.commit()
    return {"candidates": len(rows), "embedded": embedded, "failed": failed}


"""检索 — Task 11。GET /api/search?q=&mode=auto|keyword|semantic

- keyword:对结果 HTML 与 PDF 文件名做关键词(ILIKE)检索。
- semantic:用嵌入向量在 pgvector 上做余弦相似检索。
- auto:有可用嵌入且查询能嵌入则走 semantic,否则降级 keyword。
嵌入需先灌入(见 POST /api/admin/reindex)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..embeddings import embed_text, html_to_text
from ..models import Case, GenerationResult

router = APIRouter(prefix="/api", tags=["search"])


def _snippet(html: str, q: str, n: int = 160) -> str:
    text = html_to_text(html)
    if q:
        i = text.lower().find(q.lower())
        if i >= 0:
            start = max(0, i - 40)
            return ("…" if start else "") + text[start : start + n] + "…"
    return text[:n] + ("…" if len(text) > n else "")


def _keyword(db: Session, q: str, limit: int) -> list[dict]:
    like = f"%{q}%"
    rows = db.execute(
        select(GenerationResult, Case)
        .join(Case, GenerationResult.case_id == Case.id)
        .where(or_(GenerationResult.html.ilike(like), Case.pdf_filename.ilike(like)))
        .order_by(GenerationResult.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "case_id": str(c.id),
            "task_id": str(r.task_id),
            "pdf_filename": c.pdf_filename,
            "tc_count": r.tc_count,
            "snippet": _snippet(r.html, q),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r, c in rows
    ]


def _semantic(db: Session, q: str, limit: int, qvec: list[float]) -> list[dict]:
    dist = GenerationResult.embedding.cosine_distance(qvec).label("dist")
    rows = db.execute(
        select(GenerationResult, Case, dist)
        .join(Case, GenerationResult.case_id == Case.id)
        .where(GenerationResult.embedding.is_not(None))
        .order_by(dist)
        .limit(limit)
    ).all()
    out = []
    for r, c, d in rows:
        out.append(
            {
                "case_id": str(c.id),
                "task_id": str(r.task_id),
                "pdf_filename": c.pdf_filename,
                "tc_count": r.tc_count,
                "score": round(1.0 - float(d), 4),  # 余弦相似度
                "snippet": _snippet(r.html, q),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    mode: str = Query("auto", pattern="^(auto|keyword|semantic)$"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    has_embeddings = (
        db.execute(
            select(func.count()).select_from(GenerationResult).where(GenerationResult.embedding.is_not(None))
        ).scalar_one()
        > 0
    )

    used = mode
    items: list[dict] = []
    if mode in ("semantic", "auto") and has_embeddings:
        qvec = embed_text(q)
        if qvec is not None:
            items = _semantic(db, q, limit, qvec)
            used = "semantic"
        elif mode == "semantic":
            used = "semantic_unavailable_fallback_keyword"
            items = _keyword(db, q, limit)
        else:
            used = "keyword"
            items = _keyword(db, q, limit)
    else:
        if mode == "semantic" and not has_embeddings:
            used = "semantic_no_index_fallback_keyword"
        else:
            used = "keyword"
        items = _keyword(db, q, limit)

    return {"query": q, "mode_used": used, "total": len(items), "items": items}

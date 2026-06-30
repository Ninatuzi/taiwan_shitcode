"""多格式导出 — Task 10。GET /api/cases/{case_id}/export?format=html|xlsx|docx

html 零依赖,始终可用;xlsx/docx 需 openpyxl / python-docx,未装时返回 503 友好提示。
"""
from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..exporters import ExportDependencyMissing, parse_result, to_docx, to_xlsx
from ..models import Case, GenerationResult
from ..rendering import render_full_page

router = APIRouter(prefix="/api/cases", tags=["export"])

_MEDIA = {
    "html": "text/html; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _content_disposition(filename: str) -> str:
    # 兼容中文文件名(RFC 5987)
    return f"attachment; filename*=UTF-8''{quote(filename)}"


@router.get("/{case_id}/export")
def export_case(
    case_id: uuid.UUID,
    format: str = Query("html", pattern="^(html|xlsx|docx)$"),
    db: Session = Depends(get_db),
) -> Response:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case 不存在")
    result = db.execute(
        select(GenerationResult)
        .where(GenerationResult.case_id == case_id)
        .order_by(GenerationResult.created_at.desc())
    ).scalars().first()
    if result is None or not result.html:
        raise HTTPException(status_code=404, detail="该 case 还没有生成结果,无法导出")

    base = (case.pdf_filename or "testcases").rsplit(".", 1)[0]

    if format == "html":
        page = render_full_page(result.html, result.tc_count)
        return Response(
            content=page,
            media_type=_MEDIA["html"],
            headers={"Content-Disposition": _content_disposition(f"{base}.html")},
        )

    # xlsx / docx
    cards = parse_result(result.html)
    try:
        data = to_xlsx(cards) if format == "xlsx" else to_docx(cards)
    except ExportDependencyMissing as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return Response(
        content=data,
        media_type=_MEDIA[format],
        headers={"Content-Disposition": _content_disposition(f"{base}.{format}")},
    )

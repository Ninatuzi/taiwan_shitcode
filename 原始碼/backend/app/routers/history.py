"""历史案例接口 — Task 9。全局共享,不绑定个人。

- GET /api/cases                列表(分页、倒序、关键词搜索)
- GET /api/cases/{case_id}       案例详情(文档信息 + 参数/结果概要)
- GET /api/cases/{case_id}/source-pdf  下载原始 PDF
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Case, CaseParam, GenerationResult
from ..schemas import CaseDetail, CaseListItem, CaseListResponse

router = APIRouter(prefix="/api/cases", tags=["history"])


def _latest_tc_count(db: Session, case_id: uuid.UUID) -> int | None:
    r = db.execute(
        select(GenerationResult.tc_count)
        .where(GenerationResult.case_id == case_id)
        .order_by(GenerationResult.created_at.desc())
    ).first()
    return r[0] if r else None


@router.get("", response_model=CaseListResponse)
@router.get("/", response_model=CaseListResponse)
def list_cases(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="按 PDF 文件名关键词搜索"),
) -> CaseListResponse:
    stmt = select(Case)
    count_stmt = select(func.count()).select_from(Case)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Case.pdf_filename.ilike(like))
        count_stmt = count_stmt.where(Case.pdf_filename.ilike(like))

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Case.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    items = [
        CaseListItem(
            case_id=c.id,
            pdf_filename=c.pdf_filename,
            pdf_page_count=c.pdf_page_count,
            status=c.status,
            csv_filename=c.csv_filename,
            csv_param_count=c.csv_param_count,
            csv_format=c.csv_format,
            latest_tc_count=_latest_tc_count(db, c.id),
            created_at=c.created_at,
        )
        for c in rows
    ]
    return CaseListResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{case_id}", response_model=CaseDetail)
def case_detail(case_id: uuid.UUID, db: Session = Depends(get_db)) -> CaseDetail:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case 不存在")
    param_count = db.execute(
        select(func.count()).select_from(CaseParam).where(CaseParam.case_id == case_id)
    ).scalar_one()
    return CaseDetail(
        case_id=case.id,
        pdf_filename=case.pdf_filename,
        pdf_page_count=case.pdf_page_count,
        chapters=case.chapters or [],
        status=case.status,
        csv_filename=case.csv_filename,
        csv_param_count=case.csv_param_count,
        csv_format=case.csv_format,
        param_count=param_count,
        latest_tc_count=_latest_tc_count(db, case.id),
        created_at=case.created_at,
        expire_at=case.expire_at,
    )


@router.get("/{case_id}/source-pdf")
def source_pdf(case_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case 不存在")
    if not case.pdf_path or not Path(case.pdf_path).exists():
        raise HTTPException(status_code=404, detail="原始 PDF 文件不存在(可能已被清理)")
    return FileResponse(
        case.pdf_path, media_type="application/pdf", filename=case.pdf_filename or "source.pdf"
    )

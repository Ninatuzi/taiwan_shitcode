"""案例上传与解析 — Task 2（PDF）、Task 3（CSV）。

去掉旧的模块级 _state，改为每次作业一条 case 记录，按 case_id 隔离。
写入顺序：建 case_id → 建目录 → 落盘 → 成功后写库；失败回滚（删目录）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pypdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.csv_utils import parse_csv
from backend.pdf_utils import extract_chapters

from .. import storage
from ..config import get_settings
from ..db import get_db
from ..models import Case, CaseParam, OpLog
from ..schemas import UploadCsvResponse, UploadPdfResponse

router = APIRouter(prefix="/api/cases", tags=["cases"])
_settings = get_settings()


def _check_size(content: bytes) -> None:
    if len(content) > _settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过上限 {_settings.max_upload_mb}MB",
        )


@router.post("/upload-pdf", response_model=UploadPdfResponse)
async def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadPdfResponse:
    filename = file.filename or "upload.pdf"
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="仅接受 PDF 文件")

    content = await file.read()
    _check_size(content)

    case_id = uuid.uuid4()
    # 1) 落盘
    pdf_path = storage.save_file(case_id, "source.pdf", content)

    # 2) 解析（失败则回滚删目录）
    try:
        chapters = extract_chapters(pdf_path)
        reader = pypdf.PdfReader(pdf_path)
        page_count = len(reader.pages)
    except Exception as e:
        storage.remove_case_dir(case_id)
        raise HTTPException(status_code=400, detail=f"PDF 解析失败: {e}") from e

    # 3) 写库
    try:
        case = Case(
            id=case_id,
            pdf_filename=filename,
            pdf_path=pdf_path,
            pdf_page_count=page_count,
            chapters=chapters,
            status="created",
        )
        db.add(case)
        db.add(OpLog(action="upload_pdf", case_id=case_id, detail={"filename": filename, "pages": page_count}))
        db.commit()
    except Exception as e:
        db.rollback()
        storage.remove_case_dir(case_id)
        raise HTTPException(status_code=500, detail=f"写库失败: {e}") from e

    return UploadPdfResponse(
        case_id=case_id,
        pdf_filename=filename,
        pdf_page_count=page_count,
        chapters=chapters,
    )


@router.post("/{case_id}/upload-csv", response_model=UploadCsvResponse)
async def upload_csv(
    case_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadCsvResponse:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case 不存在")

    filename = file.filename or "upload.csv"
    if Path(filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="仅接受 CSV 文件")

    content = await file.read()
    _check_size(content)

    # 1) 落盘
    csv_path = storage.save_file(case_id, "params.csv", content)

    # 2) 解析（失败回滚：删 csv 文件，不动 PDF）
    try:
        params, diag = parse_csv(csv_path)
    except Exception as e:
        try:
            Path(csv_path).unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"CSV 解析失败: {e}") from e

    csv_format = "ti_data_flash" if diag.startswith("TI") else "generic"

    # 3) 写库：清掉该 case 旧参数，再写新参数（固定语义列 + raw jsonb）
    try:
        for p in case.params:
            db.delete(p)
        db.flush()
        for p in params:
            db.add(
                CaseParam(
                    case_id=case_id,
                    param_class=(p.get("class") or None),
                    subclass=(p.get("subclass") or None),
                    name=p.get("name", ""),
                    value=p.get("value"),
                    unit=(p.get("unit") or None),
                    min_value=(p.get("min") or None),
                    max_value=(p.get("max") or None),
                    raw=p,
                )
            )
        case.csv_filename = filename
        case.csv_path = csv_path
        case.csv_param_count = len(params)
        case.csv_format = csv_format
        db.add(OpLog(action="upload_csv", case_id=case_id, detail={"filename": filename, "count": len(params), "format": csv_format}))
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"写库失败: {e}") from e

    return UploadCsvResponse(case_id=case_id, count=len(params), csv_format=csv_format, diag=diag)

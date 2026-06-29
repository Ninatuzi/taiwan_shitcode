"""生成与结果查看 — Task 6（同步版）。

- POST /api/cases/{case_id}/generate     提交生成（同步执行，返回 HTML）
- GET  /api/cases/{case_id}/result        取最新生成结果（JSON）
- GET  /api/cases/{case_id}/result.html   把结果渲染成完整 HTML 页面，浏览器可直接看
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import generation
from ..config import get_settings
from ..db import get_db
from ..models import Case, GenerationResult
from ..schemas import GenerateRequest, GenerateResponse, ResultResponse

router = APIRouter(prefix="/api/cases", tags=["generate"])


# 渲染结果页用的内嵌样式（与测试卡片的 class 对应）。
_RESULT_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,'Microsoft JhengHei',sans-serif;background:#f5f6f8;margin:0;padding:24px;color:#1f2733}
h1{font-size:20px;margin:0 0 16px}
.tc-section{margin-bottom:28px}
.tc-section>h2{font-size:17px;color:#0b5fa5;border-left:4px solid #0b5fa5;padding-left:10px;margin:18px 0 12px}
.tc-card{background:#fff;border:1px solid #e3e7ee;border-radius:10px;margin:0 0 14px;box-shadow:0 1px 3px rgba(0,0,0,.05);overflow:hidden}
.tc-header{display:flex;align-items:center;gap:10px;background:#0b5fa5;color:#fff;padding:8px 14px}
.tc-id{font-weight:700;background:rgba(255,255,255,.2);padding:2px 8px;border-radius:6px;font-size:13px}
.tc-name{font-weight:600}
.tc-body{padding:6px 14px 12px}
.tc-row{display:flex;gap:12px;padding:8px 0;border-bottom:1px dashed #eef1f5}
.tc-row:last-child{border-bottom:none}
.tc-label{flex:0 0 90px;font-weight:600;color:#54607a}
.tc-value{flex:1}
.tc-value ol{margin:0;padding-left:18px}
.pass-row .tc-value{color:#137a3f;font-weight:600}
.empty{color:#888}
"""


@router.post("/{case_id}/generate", response_model=GenerateResponse)
def generate(
    case_id: uuid.UUID, req: GenerateRequest, db: Session = Depends(get_db)
) -> GenerateResponse:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case 不存在")
    if not req.selected_titles:
        raise HTTPException(status_code=400, detail="未选择任何章节")

    valid = {ch.get("title") for ch in (case.chapters or [])}
    unknown = [t for t in req.selected_titles if t not in valid]
    if unknown:
        raise HTTPException(status_code=400, detail=f"章节不存在: {unknown}")

    try:
        task = generation.run_generation(db, case, req.selected_titles)
    except Exception as e:  # 模型/网络错误等
        s = get_settings()
        raise HTTPException(
            status_code=502,
            detail=f"生成失败 (endpoint={s.llm_base_url}, model={s.llm_model}): {e}",
        ) from e

    result = db.execute(
        select(GenerationResult).where(GenerationResult.task_id == task.id)
    ).scalar_one_or_none()

    return GenerateResponse(
        task_id=task.id,
        case_id=case.id,
        status=task.status,
        chapters_generated=task.total_chapters,
        tc_count=result.tc_count if result else None,
        html=result.html if result else "",
    )


def _latest_result(db: Session, case_id: uuid.UUID) -> GenerationResult | None:
    return db.execute(
        select(GenerationResult)
        .where(GenerationResult.case_id == case_id)
        .order_by(GenerationResult.created_at.desc())
    ).scalars().first()


@router.get("/{case_id}/result", response_model=ResultResponse)
def get_result(case_id: uuid.UUID, db: Session = Depends(get_db)) -> ResultResponse:
    result = _latest_result(db, case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="该 case 还没有生成结果")
    return ResultResponse(
        case_id=case_id, task_id=result.task_id, tc_count=result.tc_count, html=result.html
    )


@router.get("/{case_id}/result.html")
def get_result_html(case_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    result = _latest_result(db, case_id)
    body = (
        result.html
        if result and result.html
        else '<p class="empty">该 case 还没有生成结果。</p>'
    )
    tc = result.tc_count if result else 0
    page = (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>测试用例结果</title><style>{_RESULT_CSS}</style></head><body>"
        f"<h1>生成的测试用例（共 {tc} 条）</h1>{body}</body></html>"
    )
    return Response(content=page, media_type="text/html; charset=utf-8")

"""API 输入/输出 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class Chapter(BaseModel):
    title: str
    page_start: int
    page_end: int
    level: int


class LLMInfo(BaseModel):
    base_url: str
    model: str
    api_key_set: bool


class HealthResponse(BaseModel):
    status: str
    db: bool
    redis: bool
    llm: LLMInfo


class UploadPdfResponse(BaseModel):
    case_id: uuid.UUID
    pdf_filename: str
    pdf_page_count: int
    chapters: list[Chapter]


class UploadCsvResponse(BaseModel):
    case_id: uuid.UUID
    count: int
    csv_format: str | None
    diag: str


class CleanupResponse(BaseModel):
    scanned: int
    deleted: int
    skipped_running: int
    deleted_ids: list[str]
    skipped_ids: list[str]


class GenerateRequest(BaseModel):
    selected_titles: list[str]
    mode: str = "free"  # free=模型自由生成(Task6) | engine=覆盖引擎枚举(Task8)


class CoverageRequest(BaseModel):
    selected_titles: list[str]
    strength: str | None = None  # pairwise(默认) | full


class GenerateResponse(BaseModel):
    task_id: uuid.UUID
    case_id: uuid.UUID
    status: str
    chapters_generated: int
    tc_count: int | None
    html: str


class ResultResponse(BaseModel):
    case_id: uuid.UUID
    task_id: uuid.UUID
    tc_count: int | None
    html: str


class CaseListItem(BaseModel):
    case_id: uuid.UUID
    pdf_filename: str
    pdf_page_count: int
    status: str
    csv_filename: str | None
    csv_param_count: int | None
    csv_format: str | None
    latest_tc_count: int | None
    created_at: datetime


class CaseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CaseListItem]


class CaseDetail(BaseModel):
    case_id: uuid.UUID
    pdf_filename: str
    pdf_page_count: int
    chapters: list[Chapter]
    status: str
    csv_filename: str | None
    csv_param_count: int | None
    csv_format: str | None
    param_count: int
    latest_tc_count: int | None
    created_at: datetime
    expire_at: datetime

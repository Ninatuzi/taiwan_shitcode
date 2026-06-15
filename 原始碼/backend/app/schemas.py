"""API 输入/输出 Pydantic 模型。"""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class Chapter(BaseModel):
    title: str
    page_start: int
    page_end: int
    level: int


class HealthResponse(BaseModel):
    status: str
    db: bool
    redis: bool


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

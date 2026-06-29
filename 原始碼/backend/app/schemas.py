"""API 输入/输出 Pydantic 模型。"""
from __future__ import annotations

import uuid

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

"""ORM 数据模型 — 对应指令书第 4 节的 5 张表。

通用设计，不绑定任何特定 CSV 格式：case_params 只固定语义列，
格式特有字段进 raw jsonb。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import get_settings

_EMBED_DIM = get_settings().embed_dim


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expire_at() -> datetime:
    return _now() + timedelta(days=get_settings().file_retention_days)


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    pdf_filename: Mapped[str] = mapped_column(String(512))
    pdf_path: Mapped[str] = mapped_column(String(1024))
    pdf_page_count: Mapped[int] = mapped_column(Integer, default=0)
    # chapters: [{title, page_start, page_end, level}, ...]
    chapters: Mapped[list] = mapped_column(JSONB, default=list)

    csv_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    csv_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    csv_param_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csv_format: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # created / analyzing / done / failed
    status: Mapped[str] = mapped_column(String(32), default="created")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_expire_at)

    params: Mapped[list["CaseParam"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    tasks: Mapped[list["GenerationTask"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    results: Mapped[list["GenerationResult"]] = relationship(back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_cases_created_at", "created_at"),
        Index("ix_cases_status", "status"),
        Index("ix_cases_expire_at", "expire_at"),
    )


class CaseParam(Base):
    __tablename__ = "case_params"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE")
    )
    param_class: Mapped[str | None] = mapped_column(String(256), nullable=True)
    subclass: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str] = mapped_column(Text)
    # 数值列以文本原样存，避免格式/精度丢失。
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    min_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 原始整行：容纳 offset/formula/flags/default/raw_value 等格式特有列。
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)

    case: Mapped["Case"] = relationship(back_populates="params")

    __table_args__ = (
        Index("ix_case_params_case_id", "case_id"),
        Index("ix_case_params_case_class_sub", "case_id", "param_class", "subclass"),
        Index("ix_case_params_name", "name"),
    )


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE")
    )
    selected_titles: Mapped[list] = mapped_column(JSONB, default=list)
    # queued / running / done / failed / canceled
    status: Mapped[str] = mapped_column(String(32), default="queued")
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_chapters: Mapped[int] = mapped_column(Integer, default=0)
    current_chapter: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="tasks")
    results: Mapped[list["GenerationResult"]] = relationship(back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_generation_tasks_case_id", "case_id"),
        Index("ix_generation_tasks_status", "status"),
        Index("ix_generation_tasks_created_at", "created_at"),
    )


class GenerationResult(Base):
    __tablename__ = "generation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_tasks.id", ondelete="CASCADE")
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE")
    )
    html: Mapped[str] = mapped_column(Text, default="")
    tc_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 语义检索用；可空（Task 11 才填充）。
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    task: Mapped["GenerationTask"] = relationship(back_populates="results")
    case: Mapped["Case"] = relationship(back_populates="results")

    __table_args__ = (
        Index("ix_generation_results_case_id", "case_id"),
        Index("ix_generation_results_task_id", "task_id"),
        # embedding 的 HNSW 索引在 schema 初始化时单独建（需指定 ops）。
    )


class OpLog(Base):
    __tablename__ = "op_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(128))
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    __table_args__ = (
        Index("ix_op_logs_created_at", "created_at"),
        Index("ix_op_logs_action", "action"),
    )

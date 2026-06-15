"""建表与扩展初始化 — 对应 Task 1。

用法（建库建用户见部署文档 / scripts/dev_bootstrap.sh）：
    python -m backend.app.schema          # 建扩展 + 建表 + 建 HNSW 索引
    python -m backend.app.schema --drop   # 先删后建（危险，仅开发用）
"""
from __future__ import annotations

import argparse

from sqlalchemy import text

from .db import engine
from .models import Base


def enable_pgvector() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def create_hnsw_index() -> None:
    """为 generation_results.embedding 建 HNSW 索引（余弦距离）。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_generation_results_embedding_hnsw "
                "ON generation_results USING hnsw (embedding vector_cosine_ops)"
            )
        )


def init_db(drop: bool = False) -> None:
    enable_pgvector()
    if drop:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    create_hnsw_index()


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 BMS 平台数据库表结构")
    parser.add_argument("--drop", action="store_true", help="先删除所有表再重建（危险）")
    args = parser.parse_args()
    init_db(drop=args.drop)
    # 报告建了哪些表
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
        ).fetchall()
    print("已建表:", ", ".join(r[0] for r in rows))


if __name__ == "__main__":
    main()

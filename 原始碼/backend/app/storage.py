"""文件存储隔离 + 过期清理 — 对应指令书第 6 节、Task 4。

- 文件按 case_id 分目录存本地：DATA_DIR/<case_id>/source.pdf | params.csv
- 库里只存相对/绝对路径
- 写入顺序：建目录 → 落盘 → 成功后写库（调用方负责写库）
- 清理：扫 expire_at 过期 → 删目录 + 删记录；幂等；running 任务跳过；记 op_logs
"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Case, CaseParam, GenerationResult, GenerationTask, OpLog

_settings = get_settings()


def data_root() -> Path:
    root = Path(_settings.data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def case_dir(case_id: uuid.UUID | str) -> Path:
    return data_root() / str(case_id)


def save_file(case_id: uuid.UUID | str, filename: str, content: bytes) -> str:
    """先建目录再落盘，返回绝对路径。调用方在落盘成功后再写库。"""
    d = case_dir(case_id)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / filename
    dest.write_bytes(content)
    return str(dest)


def remove_case_dir(case_id: uuid.UUID | str) -> None:
    d = case_dir(case_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def cleanup_expired(db: Session) -> dict:
    """删除已过期的 case：跳过仍有 running 任务的 case；幂等。

    返回统计 {scanned, deleted, skipped_running}。
    """
    now = datetime.now(timezone.utc)
    expired = db.execute(select(Case).where(Case.expire_at < now)).scalars().all()

    deleted: list[str] = []
    skipped: list[str] = []

    for case in expired:
        running = db.execute(
            select(GenerationTask.id).where(
                GenerationTask.case_id == case.id,
                GenerationTask.status == "running",
            )
        ).first()
        if running:
            skipped.append(str(case.id))
            continue

        cid = case.id
        # 先删磁盘目录（幂等），再删库记录。
        remove_case_dir(cid)
        # 子表通过 FK ondelete=CASCADE 也会清，但显式删更稳妥且可计数。
        db.execute(delete(GenerationResult).where(GenerationResult.case_id == cid))
        db.execute(delete(GenerationTask).where(GenerationTask.case_id == cid))
        db.execute(delete(CaseParam).where(CaseParam.case_id == cid))
        db.execute(delete(Case).where(Case.id == cid))
        db.add(OpLog(action="cleanup_case", case_id=cid, detail={"expire_at": case.expire_at.isoformat()}))
        deleted.append(str(cid))

    db.commit()

    result = {
        "scanned": len(expired),
        "deleted": len(deleted),
        "skipped_running": len(skipped),
        "deleted_ids": deleted,
        "skipped_ids": skipped,
    }
    return result

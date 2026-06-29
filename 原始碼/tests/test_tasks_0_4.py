"""Task 0~4 自测：健康检查、上传解析PDF、上传解析CSV、过期清理。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .conftest import make_generic_csv_bytes, make_pdf_bytes, make_ti_csv_bytes


# ── Task 0 ──
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["db"] is True, "DB 未连通"
    assert data["redis"] is True, "Redis 未连通"
    assert data["status"] == "ok"
    # 透出当前生效的 LLM 配置(便于排查连的哪个端点)
    assert "llm" in data
    assert data["llm"]["base_url"]
    assert data["llm"]["model"]
    assert "api_key_set" in data["llm"]


# ── Task 2 ──
def test_upload_pdf_and_isolation(client):
    pdf1 = make_pdf_bytes(["1. Overvoltage Protection", "2. Undervoltage Protection"])
    pdf2 = make_pdf_bytes(["1. Overcurrent Discharge", "2. Short Circuit"])

    r1 = client.post("/api/cases/upload-pdf", files={"file": ("spec1.pdf", pdf1, "application/pdf")})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["pdf_page_count"] == 2
    assert len(d1["chapters"]) >= 2
    titles1 = [c["title"] for c in d1["chapters"]]
    assert any("Overvoltage" in t for t in titles1)

    r2 = client.post("/api/cases/upload-pdf", files={"file": ("spec2.pdf", pdf2, "application/pdf")})
    assert r2.status_code == 200, r2.text
    d2 = r2.json()

    # 两个 case 隔离：id 不同，章节不同
    assert d1["case_id"] != d2["case_id"]
    titles2 = [c["title"] for c in d2["chapters"]]
    assert any("Overcurrent" in t for t in titles2)
    assert titles1 != titles2

    # 磁盘有文件，库里有记录
    from backend.app.config import get_settings
    from backend.app.db import SessionLocal
    from backend.app.models import Case

    case_dir = Path(get_settings().data_dir) / d1["case_id"]
    assert (case_dir / "source.pdf").exists(), "PDF 未落盘"

    db = SessionLocal()
    try:
        case = db.get(Case, uuid.UUID(d1["case_id"]))
        assert case is not None and case.status == "created"
        assert case.pdf_page_count == 2
    finally:
        db.close()


def test_upload_pdf_rejects_non_pdf(client):
    r = client.post("/api/cases/upload-pdf", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


# ── Task 3 ──
def test_upload_csv_ti_format(client):
    pdf = make_pdf_bytes(["1. CUV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    case_id = rc.json()["case_id"]

    r = client.post(
        f"/api/cases/{case_id}/upload-csv",
        files={"file": ("flash.csv", make_ti_csv_bytes(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 3
    assert data["csv_format"] == "ti_data_flash"

    # 校验 min/max 正确入库，格式特有列进 raw
    from backend.app.db import SessionLocal
    from backend.app.models import CaseParam

    db = SessionLocal()
    try:
        params = db.query(CaseParam).filter(CaseParam.case_id == uuid.UUID(case_id)).all()
        assert len(params) == 3
        cuv = next(p for p in params if "CUV" in p.name)
        assert cuv.min_value == "2000"
        assert cuv.max_value == "3000"
        assert cuv.unit == "mV"
        assert cuv.param_class == "Protections"
        assert cuv.subclass == "CUV"
        # raw 保存原始整行（含 flags 等格式特有列）
        assert cuv.raw.get("flags") == "F8"
    finally:
        db.close()


def test_upload_csv_generic_format(client):
    pdf = make_pdf_bytes(["1. Voltage Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    case_id = rc.json()["case_id"]

    r = client.post(
        f"/api/cases/{case_id}/upload-csv",
        files={"file": ("params.csv", make_generic_csv_bytes(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 2
    assert data["csv_format"] == "generic"


# ── Task 4 ──
def test_cleanup_expired_and_skip_running(client):
    from backend.app.config import get_settings
    from backend.app.db import SessionLocal
    from backend.app.models import Case, GenerationTask
    from backend.app import storage

    # 造两条过期 case：A 无运行任务（应删），B 有 running 任务（应跳过）
    db = SessionLocal()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    try:
        case_a = Case(pdf_filename="a.pdf", pdf_path="x", chapters=[], expire_at=past)
        case_b = Case(pdf_filename="b.pdf", pdf_path="y", chapters=[], expire_at=past)
        db.add_all([case_a, case_b])
        db.flush()
        # 落两个目录
        storage.save_file(case_a.id, "source.pdf", b"%PDF-1.4 a")
        storage.save_file(case_b.id, "source.pdf", b"%PDF-1.4 b")
        db.add(GenerationTask(case_id=case_b.id, status="running", selected_titles=[]))
        db.commit()
        a_id, b_id = case_a.id, case_b.id
    finally:
        db.close()

    r = client.post("/api/admin/cleanup")
    assert r.status_code == 200, r.text
    res = r.json()
    assert str(a_id) in res["deleted_ids"]
    assert str(b_id) in res["skipped_ids"]

    # A 目录与记录被清，B 保留
    data_dir = Path(get_settings().data_dir)
    assert not (data_dir / str(a_id)).exists()
    assert (data_dir / str(b_id)).exists()

    db = SessionLocal()
    try:
        assert db.get(Case, a_id) is None
        assert db.get(Case, b_id) is not None
    finally:
        db.close()

    # 幂等：再次清理不报错
    r2 = client.post("/api/admin/cleanup")
    assert r2.status_code == 200

"""Task 11 检索自测:关键词检索 + pgvector 语义检索(嵌入 mock)。"""
from __future__ import annotations

import backend.app.embeddings as embeddings
import backend.app.llm as llm
import pytest
from sqlalchemy import text as _sql_text

from backend.app.config import get_settings
from backend.app.db import SessionLocal

from .conftest import make_pdf_bytes

_DIM = get_settings().embed_dim


@pytest.fixture(autouse=True)
def _clean_db():
    # 每个检索用例前清空业务表,保证语义排序确定、互不干扰
    db = SessionLocal()
    try:
        db.execute(_sql_text("TRUNCATE cases, case_params, generation_tasks, generation_results, op_logs CASCADE"))
        db.commit()
    finally:
        db.close()
    yield


def _gen_case(client, monkeypatch, heading: str, card_text: str) -> str:
    pdf = make_pdf_bytes([heading])
    rc = client.post("/api/cases/upload-pdf", files={"file": (f"{heading}.pdf", pdf, "application/pdf")})
    d = rc.json()
    cid, title = d["case_id"], d["chapters"][0]["title"]
    card = f'<div class="tc-card"><div class="tc-header"><span class="tc-id">TC-01</span>' \
           f'<span class="tc-name">{card_text}</span></div></div>'
    monkeypatch.setattr(llm, "stream_chat", lambda prompt: iter([card]))
    client.post(f"/api/cases/{cid}/generate", json={"selected_titles": [title]})
    return cid


def test_keyword_search(client, monkeypatch):
    _gen_case(client, monkeypatch, "2.9 Overtemperature Charge", "过温保护测试")
    _gen_case(client, monkeypatch, "3.1 Overcurrent Discharge", "过流放电测试")

    r = client.get("/api/search", params={"q": "过温", "mode": "keyword"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode_used"] == "keyword"
    assert data["total"] >= 1
    assert all("过温" in it["snippet"] or "Overtemperature" in (it["pdf_filename"] or "") for it in data["items"])

    # 文件名搜索
    r2 = client.get("/api/search", params={"q": "Overcurrent"})
    assert any("Overcurrent" in (it["pdf_filename"] or "") for it in r2.json()["items"])

    # 无结果
    r3 = client.get("/api/search", params={"q": "完全不存在xyz"})
    assert r3.json()["total"] == 0


def test_semantic_search_with_mocked_embeddings(client, monkeypatch):
    cid_otc = _gen_case(client, monkeypatch, "2.9 Overtemperature", "OTC 过温")
    cid_occ = _gen_case(client, monkeypatch, "3.1 Overcurrent", "OCC 过流")

    # mock 嵌入:含"过温/OTC"→[1,0,...];含"过流/OCC"→[0,1,...];查询同理
    def fake_embed(text: str):
        v = [0.0] * _DIM
        t = text or ""
        if "过温" in t or "OTC" in t or "温" in t:
            v[0] = 1.0
        elif "过流" in t or "OCC" in t or "流" in t:
            v[1] = 1.0
        else:
            v[2] = 1.0
        return v

    monkeypatch.setattr(embeddings, "embed_text", fake_embed)
    # search.py 内是 `from ..embeddings import embed_text`,需 patch 其引用
    import backend.app.routers.search as search_mod
    monkeypatch.setattr(search_mod, "embed_text", fake_embed)
    import backend.app.routers.admin as admin_mod
    monkeypatch.setattr(admin_mod, "embed_text", fake_embed)

    # 灌入向量
    rr = client.post("/api/admin/reindex")
    assert rr.status_code == 200, rr.text
    assert rr.json()["embedded"] >= 2

    # 语义检索"过温"应把 OTC 案例排在最前
    r = client.get("/api/search", params={"q": "过温保护", "mode": "semantic"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode_used"] == "semantic"
    assert data["total"] >= 2
    assert data["items"][0]["case_id"] == cid_otc
    assert data["items"][0]["score"] >= data["items"][-1]["score"]


def test_semantic_falls_back_to_keyword_when_no_index(client, monkeypatch):
    # 没有任何嵌入时,mode=semantic 自动降级关键词
    _gen_case(client, monkeypatch, "5.5 Short Circuit", "短路保护")
    r = client.get("/api/search", params={"q": "短路", "mode": "semantic"})
    assert r.status_code == 200
    assert r.json()["mode_used"] == "semantic_no_index_fallback_keyword"
    assert r.json()["total"] >= 1

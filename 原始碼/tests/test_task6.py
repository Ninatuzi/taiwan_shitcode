"""Task 6 自测：生成调用层 + 生成接口 + 结果查看。

模型调用被 mock（沙箱连不到内网 vLLM）。真实模型效果在部署服务器上验证。
重点验证：Prompt 组装、分章节流程、HTML 拼装、落库、结果页渲染、错误处理。
"""
from __future__ import annotations

import uuid

import backend.app.llm as llm
from backend.app import generation

from .conftest import make_pdf_bytes, make_ti_csv_bytes


def _make_case_with_csv(client) -> tuple[str, str]:
    pdf = make_pdf_bytes(["1. CUV Protection", "2. COV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    data = rc.json()
    case_id = data["case_id"]
    title = data["chapters"][0]["title"]
    client.post(
        f"/api/cases/{case_id}/upload-csv",
        files={"file": ("f.csv", make_ti_csv_bytes(), "text/csv")},
    )
    return case_id, title


_FAKE_CARD = (
    '<div class="tc-card"><div class="tc-header">'
    '<span class="tc-id">TC-01</span><span class="tc-name">下界测试</span></div>'
    '<div class="tc-body"><div class="tc-row"><div class="tc-label">前置條件</div>'
    '<div class="tc-value">CUV=2000mV</div></div></div></div>'
)


def test_generate_and_result(client, monkeypatch):
    case_id, title = _make_case_with_csv(client)

    # mock 模型：流式返回一张卡片（带 ```html 围栏以验证剥离）
    def fake_stream(prompt: str):
        assert title in prompt  # Prompt 里应包含章节标题
        assert "BVA" in prompt  # 沿用了 BVA 误差规范
        yield "```html\n"
        yield _FAKE_CARD
        yield "\n```"

    monkeypatch.setattr(llm, "stream_chat", fake_stream)

    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": [title]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "done"
    assert data["chapters_generated"] == 1
    assert data["tc_count"] == 1
    assert 'class="tc-card"' in data["html"]
    assert f"<h2>{title}</h2>" in data["html"]
    assert "```" not in data["html"]  # 围栏已剥离

    # 结果 JSON
    rr = client.get(f"/api/cases/{case_id}/result")
    assert rr.status_code == 200
    assert rr.json()["tc_count"] == 1

    # 结果 HTML 页（可在浏览器直接看）
    rh = client.get(f"/api/cases/{case_id}/result.html")
    assert rh.status_code == 200
    assert "text/html" in rh.headers["content-type"]
    assert "tc-card" in rh.text
    assert ".tc-card{" in rh.text  # 内嵌了渲染样式


def test_generate_multi_chapter(client, monkeypatch):
    pdf = make_pdf_bytes(["1. CUV Protection", "2. COV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    d = rc.json()
    case_id = d["case_id"]
    titles = [c["title"] for c in d["chapters"][:2]]

    monkeypatch.setattr(llm, "stream_chat", lambda prompt: iter([_FAKE_CARD]))

    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": titles})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["chapters_generated"] == 2
    assert data["tc_count"] == 2  # 两章各一张卡片
    assert data["html"].count("<h2>") == 2


def test_generate_rejects_unknown_chapter(client):
    pdf = make_pdf_bytes(["1. CUV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    case_id = rc.json()["case_id"]
    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": ["不存在的章节"]})
    assert r.status_code == 400


def test_generate_model_error_sets_failed(client, monkeypatch):
    case_id, title = _make_case_with_csv(client)

    def boom(prompt: str):
        raise RuntimeError("模型连接超时")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", boom)
    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": [title]})
    assert r.status_code == 502
    assert "生成失败" in r.json()["detail"]

    # 任务应标记为 failed，case 状态为 failed
    from backend.app.db import SessionLocal
    from backend.app.models import Case, GenerationTask

    db = SessionLocal()
    try:
        case = db.get(Case, uuid.UUID(case_id))
        assert case.status == "failed"
        tasks = db.query(GenerationTask).filter(GenerationTask.case_id == uuid.UUID(case_id)).all()
        assert any(t.status == "failed" for t in tasks)
    finally:
        db.close()

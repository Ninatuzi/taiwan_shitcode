"""Task 9(历史接口)+ Task 10(导出)自测。"""
from __future__ import annotations

import uuid

import backend.app.llm as llm

from .conftest import make_pdf_bytes, make_ti_csv_bytes

_CARD = (
    '<div class="tc-card"><div class="tc-header">'
    '<span class="tc-id">TC-01</span><span class="tc-name">OTC_温度等于阈值_Alert触发</span></div>'
    '<div class="tc-body">'
    '<div class="tc-row"><div class="tc-label">前置条件</div>'
    '<div class="tc-value">OTC Threshold = 60.0°C<br>OTC Delay = 5s</div></div>'
    '<div class="tc-row"><div class="tc-label">测试步骤</div>'
    '<div class="tc-value"><ol><li>设温度=60.0°C</li><li>读 SafetyAlert()[OTC]</li></ol></div></div>'
    '<div class="tc-row"><div class="tc-label">预期行为</div><div class="tc-value">Alert=1</div></div>'
    '<div class="tc-row pass-row"><div class="tc-label">Pass 判定</div><div class="tc-value">OTC=1</div></div>'
    '</div></div>'
)


def _make_generated_case(client, monkeypatch) -> tuple[str, str]:
    pdf = make_pdf_bytes(["2.9 Overtemperature in Charge Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("spec.pdf", pdf, "application/pdf")})
    data = rc.json()
    case_id, title = data["case_id"], data["chapters"][0]["title"]
    client.post(f"/api/cases/{case_id}/upload-csv", files={"file": ("p.csv", make_ti_csv_bytes(), "text/csv")})
    monkeypatch.setattr(llm, "stream_chat", lambda prompt: iter([_CARD]))
    client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": [title]})
    return case_id, title


# ── Task 9 ──
def test_list_cases_pagination_and_search(client, monkeypatch):
    case_id, _ = _make_generated_case(client, monkeypatch)

    r = client.get("/api/cases?page=1&page_size=10")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    assert any(it["case_id"] == case_id for it in data["items"])
    item = next(it for it in data["items"] if it["case_id"] == case_id)
    assert item["latest_tc_count"] == 1
    assert item["csv_param_count"] == 3

    # 关键词搜索
    r2 = client.get("/api/cases?q=spec")
    assert r2.status_code == 200
    assert any(it["case_id"] == case_id for it in r2.json()["items"])
    r3 = client.get("/api/cases?q=不存在的关键词xyz")
    assert all(it["case_id"] != case_id for it in r3.json()["items"])


def test_case_detail(client, monkeypatch):
    case_id, _ = _make_generated_case(client, monkeypatch)
    r = client.get(f"/api/cases/{case_id}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["case_id"] == case_id
    assert d["param_count"] == 3
    assert d["latest_tc_count"] == 1
    assert len(d["chapters"]) >= 1

    assert client.get(f"/api/cases/{uuid.uuid4()}").status_code == 404


def test_source_pdf_download(client, monkeypatch):
    case_id, _ = _make_generated_case(client, monkeypatch)
    r = client.get(f"/api/cases/{case_id}/source-pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


# ── Task 10 ──
def test_export_html(client, monkeypatch):
    case_id, _ = _make_generated_case(client, monkeypatch)
    r = client.get(f"/api/cases/{case_id}/export?format=html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert "tc-card" in r.text
    assert "OTC Threshold = 60.0°C" in r.text


def test_export_xlsx_docx(client, monkeypatch):
    case_id, _ = _make_generated_case(client, monkeypatch)
    for fmt, magic in [("xlsx", b"PK"), ("docx", b"PK")]:
        r = client.get(f"/api/cases/{case_id}/export?format={fmt}")
        # 装了 openpyxl/python-docx → 200 且是 zip(PK);没装 → 503 友好提示
        assert r.status_code in (200, 503), r.text
        if r.status_code == 200:
            assert r.content[:2] == magic
            assert "attachment" in r.headers["content-disposition"]


def test_export_invalid_format_and_no_result(client):
    # 没有结果的 case 导出 → 404
    pdf = make_pdf_bytes(["1. X"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("a.pdf", pdf, "application/pdf")})
    cid = rc.json()["case_id"]
    assert client.get(f"/api/cases/{cid}/export?format=html").status_code == 404
    # 非法格式 → 422(被 Query 校验拦下)
    assert client.get(f"/api/cases/{cid}/export?format=pdf").status_code == 422


def test_parse_result_unit():
    from backend.app.exporters import parse_result

    cards = parse_result('<section class="tc-section"><h2>2.9 OTC</h2>' + _CARD + "</section>")
    assert len(cards) == 1
    c = cards[0]
    assert c.chapter == "2.9 OTC"
    assert c.tc_id == "TC-01"
    assert "60.0°C" in c.fields["前置条件"]
    assert "读 SafetyAlert" in c.fields["测试步骤"]

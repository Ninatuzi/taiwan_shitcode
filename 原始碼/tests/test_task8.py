"""Task 8 覆盖引擎自测:BVA 边界点、pairwise 组合、约束、接口、引擎生成模式。"""
from __future__ import annotations

import backend.app.llm as llm
from backend.app import coverage, generation

from .conftest import make_pdf_bytes, make_ti_csv_bytes


# ── BVA 边界点 ──
def test_boundary_points_voltage():
    p = {"name": "CUV Threshold", "unit": "mV", "min": "2000", "max": "3000"}
    pts = coverage.boundary_points(p)
    vals = [pt.value for pt in pts]
    # 下界-误差/下界/下界+误差/正常/上界-误差/上界/上界+误差 (tol=10mV)
    assert vals == ["1990", "2000", "2010", "2500", "2990", "3000", "3010"]
    assert coverage.classify(p) == "voltage"


def test_boundary_points_generic_dedup():
    # 无可识别单位 → 误差0,只剩 min/typical/max(去重)
    p = {"name": "Count", "unit": "", "min": "0", "max": "2"}
    pts = coverage.boundary_points(p)
    assert [pt.value for pt in pts] == ["0", "1", "2"]


def test_boundary_points_skip_without_minmax():
    assert coverage.boundary_points({"name": "X", "value": "5"}) == []


# ── pairwise 组合 + 约束 ──
def test_build_plan_single_param_is_pure_bva():
    plan = coverage.build_plan([{"name": "A", "unit": "mV", "min": "2000", "max": "3000"}])
    assert plan["combination_count"] == 7  # 单参数=该参数全部边界点


def test_build_plan_two_params_pairwise_equals_full():
    params = [
        {"name": "A", "unit": "mV", "min": "2000", "max": "3000"},
        {"name": "B", "unit": "mV", "min": "4000", "max": "4500"},
    ]
    plan = coverage.build_plan(params, strength="pairwise")
    # 两个参数各 7 点,pairwise(两维)= 全两两 = 49
    assert plan["combination_count"] == 49
    assert all(set(c.keys()) == {"A", "B"} for c in plan["combinations"])


def test_build_plan_three_params_pairwise_smaller_than_full():
    params = [
        {"name": "A", "unit": "mV", "min": "2000", "max": "3000"},
        {"name": "B", "unit": "mA", "min": "10", "max": "100"},
        {"name": "C", "unit": "°C", "min": "0", "max": "60"},
    ]
    plan = coverage.build_plan(params, strength="pairwise")
    assert 49 <= plan["combination_count"] < 7 * 7 * 7  # 覆盖所有两两组合,远少于全穷举


def test_build_plan_skips_params_without_minmax():
    params = [
        {"name": "A", "unit": "mV", "min": "2000", "max": "3000"},
        {"name": "NoRange", "value": "1"},  # 无 min/max → 跳过
    ]
    plan = coverage.build_plan(params)
    assert "NoRange" in plan["skipped"]
    assert [p["name"] for p in plan["params"]] == ["A"]


# ── 接口 ──
def test_coverage_endpoint(client):
    pdf = make_pdf_bytes(["1. CUV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    d = rc.json()
    case_id, title = d["case_id"], d["chapters"][0]["title"]
    client.post(f"/api/cases/{case_id}/upload-csv", files={"file": ("f.csv", make_ti_csv_bytes(), "text/csv")})

    r = client.post(f"/api/cases/{case_id}/coverage", json={"selected_titles": [title]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_test_points"] >= 7  # CUV Threshold 至少 7 个边界点
    assert data["chapters"][0]["plan"]["combination_count"] >= 7


# ── 引擎生成模式 ──
def test_engine_prompt_lists_points():
    plan = coverage.build_plan([{"name": "CUV", "unit": "mV", "min": "2000", "max": "3000"}])
    prompt = generation.build_engine_prompt("CUV 保护", "正文", [], plan)
    assert "测试点01" in prompt
    assert "必须" in prompt and "tc-card" in prompt
    # 7 个测试点都列进了 prompt
    assert "测试点07" in prompt


def test_generate_engine_mode(client, monkeypatch):
    pdf = make_pdf_bytes(["1. CUV Protection"])
    rc = client.post("/api/cases/upload-pdf", files={"file": ("s.pdf", pdf, "application/pdf")})
    d = rc.json()
    case_id, title = d["case_id"], d["chapters"][0]["title"]
    client.post(f"/api/cases/{case_id}/upload-csv", files={"file": ("f.csv", make_ti_csv_bytes(), "text/csv")})

    card = '<div class="tc-card"><div class="tc-header"><span class="tc-id">TC-01</span></div></div>'
    monkeypatch.setattr(llm, "stream_chat", lambda prompt: iter([card]))
    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": [title], "mode": "engine"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"

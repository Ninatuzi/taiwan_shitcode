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



def test_load_template_tolerates_gbk(tmp_path, monkeypatch):
    """模板文件被存成 GBK(Windows 另存常见)时,加载不应崩溃。"""
    from backend.app import generation

    gbk_file = tmp_path / "testcase_prompt.txt"
    content = "你是资深的 BMS 固件测试工程师。{title}\n{chapter_text}\n{param_table}"
    gbk_file.write_bytes(content.encode("gbk"))  # 故意用 GBK 编码

    monkeypatch.setattr(generation, "_PROMPT_PATH", gbk_file)
    generation._load_template.cache_clear()
    try:
        loaded = generation._load_template()
        assert "你是资深的 BMS" in loaded  # 正确按 GBK 解码出中文
        # build_prompt 也应正常工作,不抛 UnicodeDecodeError
        prompt = generation.build_prompt("2.9 OTC", "正文内容", [])
        assert "2.9 OTC" in prompt
    finally:
        generation._load_template.cache_clear()



def test_clean_output_strips_nul_and_think():
    """模型输出的 NUL 与 R1 <think> 思考段应被清除。"""
    from backend.app.llm import clean_output

    raw = "<think>\n我在思考圆面积…\n</think>\n\n```html\n<div class=\"tc-card\">\x00卡片</div>\n```"
    out = clean_output(raw)
    assert "\x00" not in out          # NUL 去掉
    assert "<think>" not in out       # 思考段去掉
    assert "圆面积" not in out         # 思考内容去掉
    assert "```" not in out           # 围栏去掉
    assert 'class="tc-card"' in out   # 正文保留

    # 未闭合的 <think>(思考被截断,无 </think>)应整段丢弃
    out2 = clean_output("<think>\n无尽的思考没有结束")
    assert out2 == ""


def test_generation_strips_nul_via_model(client, monkeypatch):
    """模型返回含 NUL 与 <think> 的内容,生成应成功落库、不报 NUL 错误。"""
    case_id, title = _make_case_with_csv(client)

    def dirty_stream(prompt: str):
        yield "<think>思考中…</think>"
        yield '<div class="tc-card">\x00<div class="tc-header">'
        yield '<span class="tc-id">TC-01</span></div></div>'

    monkeypatch.setattr(llm, "stream_chat", dirty_stream)
    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": [title]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tc_count"] == 1
    assert "\x00" not in data["html"]
    assert "<think>" not in data["html"]


def test_load_template_fallback_on_garbled(tmp_path, monkeypatch):
    """模板文件乱码(解码出替换字符)时,应自动改用内置模板。"""
    from backend.app import generation

    bad = tmp_path / "testcase_prompt.txt"
    bad.write_bytes(b"\xff\xfe\xfa\xfb garbage not a template")  # 非法字节
    monkeypatch.setattr(generation, "_PROMPT_PATH", bad)
    generation._load_template.cache_clear()
    try:
        tmpl = generation._load_template()
        assert "tc-card" in tmpl  # 用了内置兜底模板
    finally:
        generation._load_template.cache_clear()



# 用户实测得到的"正常"卡片(R1 干净输出),用于回归:确保我的清洗不破坏它
_GOOD_CARD = (
    '<div class="tc-card">'
    '<div class="tc-header"><span class="tc-id">TC-01</span>'
    '<span class="tc-name">OTC_充电中_温度等于阈值_Alert触发</span></div>'
    '<div class="tc-body">'
    '<div class="tc-row"><div class="tc-label">前置条件</div>'
    '<div class="tc-value">- OTC Threshold = 60.0°C<br>- OTC Delay = 5s<br>- OTC Recovery = 40.0°C'
    '<br>- FET Options[OTFET] = 0x0000<br>- AC_STATE = 1<br>- SafetyStatus()[OTC] = 0</div></div>'
    '<div class="tc-row"><div class="tc-label">测试步骤</div><div class="tc-value"><ol>'
    '<li>确认所有参数设置正确</li><li>将温度设置为60.0°C（等于OTC Threshold）</li>'
    '<li>立即读取SafetyAlert()[OTC]，应为1</li></ol></div></div>'
    '<div class="tc-row"><div class="tc-label">预期行为</div>'
    '<div class="tc-value">触发瞬间：SafetyAlert()[OTC] = 1</div></div>'
    '<div class="tc-row pass-row"><div class="tc-label">Pass 判定</div>'
    '<div class="tc-value">SafetyAlert()[OTC] = 1（触发瞬间）</div></div>'
    '</div></div>'
)


def test_clean_output_preserves_good_card():
    """回归:干净的正常卡片(无 think/NUL)经清洗后必须原样保留,不被破坏。"""
    from backend.app.llm import clean_output

    out = clean_output(_GOOD_CARD)
    assert out == _GOOD_CARD  # 一字不差
    assert "OTC Threshold = 60.0°C" in out
    assert "OTC_充电中_温度等于阈值_Alert触发" in out
    assert out.count('class="tc-card"') == 1


def test_clean_output_keeps_card_after_think():
    """R1 先输出 <think>思考</think> 再给卡片时:思考剥掉,卡片完整保留。"""
    from backend.app.llm import clean_output

    raw = "<think>\n我需要分析 OTC 充电过温保护…\n</think>\n\n" + _GOOD_CARD
    out = clean_output(raw)
    assert "<think>" not in out and "我需要分析" not in out
    assert out == _GOOD_CARD  # 卡片部分一字不差保留


def test_generation_preserves_good_card_end_to_end(client, monkeypatch):
    """端到端:模型返回正常卡片,生成结果应完整含该卡片、tc_count=1。"""
    case_id, title = _make_case_with_csv(client)
    monkeypatch.setattr(llm, "stream_chat", lambda prompt: iter([_GOOD_CARD]))
    r = client.post(f"/api/cases/{case_id}/generate", json={"selected_titles": [title]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tc_count"] == 1
    assert "OTC Threshold = 60.0°C" in data["html"]
    assert "OTC_充电中_温度等于阈值_Alert触发" in data["html"]
    assert f"<h2>{title}</h2>" in data["html"]

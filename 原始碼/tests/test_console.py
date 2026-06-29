"""测试控制台页自测：GET / 返回自包含 HTML（无外部 CDN 依赖）。"""
from __future__ import annotations


def test_console_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # 关键元素与流程都在
    assert "测试控制台" in body
    assert "/api/cases/upload-pdf" in body
    assert "/api/cases/" in body and "/generate" in body
    assert ".tc-card{" in body  # 内嵌了卡片渲染样式
    # 不依赖外部 CDN（离线可用）
    assert "http://" not in body.replace("http://www.w3.org", "")
    assert "https://" not in body

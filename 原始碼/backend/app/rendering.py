"""结果页渲染:测试卡片的内嵌样式 + 完整 HTML 页面。

供 result.html 在线查看与 export?format=html 下载复用,避免重复。
"""
from __future__ import annotations

RESULT_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,'Microsoft JhengHei','Microsoft YaHei',sans-serif;background:#f5f6f8;margin:0;padding:24px;color:#1f2733}
h1{font-size:20px;margin:0 0 16px}
.tc-section{margin-bottom:28px}
.tc-section>h2{font-size:17px;color:#0b5fa5;border-left:4px solid #0b5fa5;padding-left:10px;margin:18px 0 12px}
.tc-card{background:#fff;border:1px solid #e3e7ee;border-radius:10px;margin:0 0 14px;box-shadow:0 1px 3px rgba(0,0,0,.05);overflow:hidden}
.tc-header{display:flex;align-items:center;gap:10px;background:#0b5fa5;color:#fff;padding:8px 14px}
.tc-id{font-weight:700;background:rgba(255,255,255,.2);padding:2px 8px;border-radius:6px;font-size:13px}
.tc-name{font-weight:600}
.tc-body{padding:6px 14px 12px}
.tc-row{display:flex;gap:12px;padding:8px 0;border-bottom:1px dashed #eef1f5}
.tc-row:last-child{border-bottom:none}
.tc-label{flex:0 0 90px;font-weight:600;color:#54607a}
.tc-value{flex:1}
.tc-value ol{margin:0;padding-left:18px}
.pass-row .tc-value{color:#137a3f;font-weight:600}
.empty{color:#888}
"""


def render_full_page(body_html: str, tc_count: int | None = 0, heading: str | None = None) -> str:
    """把测试卡片 HTML 片段包装成可独立打开/下载的完整页面。"""
    body = body_html if body_html else '<p class="empty">暂无生成结果。</p>'
    title = heading or f"生成的测试用例（共 {tc_count or 0} 条）"
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>测试用例</title><style>{RESULT_CSS}</style></head><body>"
        f"<h1>{title}</h1>{body}</body></html>"
    )

"""生成服务 — Task 6（同步版）。

复用现有核心逻辑（不重写）：
- pdf_utils：章节文本抽取、清洗、同级章节截断
- csv_utils：章节↔参数匹配（BMS 缩写词表）
分章节处理：每章单独成一个模型请求，控制输入预算，避免超上下文。

注意：本版为同步生成（便于尽快评测模型效果）。
队列/并发闸（Task 5）与 SSE 进度（Task 7）将在 M1 后续补上，
run_generation 已通过 on_event 回调预留进度钩子供 SSE 复用。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import pypdf
from sqlalchemy.orm import Session

from backend.csv_utils import match_params_for_chapters
from backend.pdf_utils import (
    clean_pdf_text,
    extract_pages_for_chapter,
    remove_repeated_lines,
    truncate_at_sibling_chapter,
)

from .config import get_settings
from .llm import strip_html_fences
from . import llm as _llm
from .models import Case, GenerationResult, GenerationTask, OpLog

_settings = get_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_param_table(matched: list[dict]) -> str:
    if not matched:
        return ""
    rows = [
        f"| {p.get('name','')} | {p.get('value','')} "
        f"| {p.get('unit') or '–'} | {p.get('min','–')} | {p.get('max','–')} |"
        for p in matched
    ]
    return (
        f"\n[本章节相关参数共 {len(matched)} 筆，測試數值請以下表為準]\n"
        "| 參數名稱 | 目前值 | 單位 | Min | Max |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


def build_prompt(title: str, chapter_text: str, matched: list[dict]) -> str:
    """单章节 Prompt（沿用旧版的卡片结构与 BVA 误差规范）。"""
    # 粗略输入预算保护：按 token≈2 字符估算，超限则截断章节正文。
    budget_chars = max(2000, _settings.llm_max_input_tokens * 2)
    if len(chapter_text) > budget_chars:
        chapter_text = chapter_text[:budget_chars] + "\n…（内容过长已截断）"

    param_table = _build_param_table(matched)
    return f"""你是專業的 BMS 固件測試工程師。以下是規格書中「{title}」章節的內容：

==[{title}]==
{chapter_text}
{param_table}
請依據上述規格內容，為「{title}」這一個章節生成 HTML 測試卡片，嚴格遵守以下規則：
- 直接輸出純 HTML 片段，只包含若干 <div class="tc-card">...</div>，不要 <html>/<head>/<body>/<style> 標籤，不要 ```html 標記，不要任何前後說明文字。
- 不要輸出 <section> 或 <h2>，只輸出 tc-card（章節標題會由程式另行包裹）。
- 每個測試案例使用以下固定 HTML 結構（TC 編號從 01 遞增）：

<div class="tc-card">
  <div class="tc-header"><span class="tc-id">TC-01</span><span class="tc-name">測試名稱</span></div>
  <div class="tc-body">
    <div class="tc-row"><div class="tc-label">前置條件</div><div class="tc-value">...</div></div>
    <div class="tc-row"><div class="tc-label">測試步驟</div><div class="tc-value"><ol><li>設定參數值</li><li>等待/觸發條件</li><li>讀取暫存器/旗標</li></ol></div></div>
    <div class="tc-row"><div class="tc-label">預期行為</div><div class="tc-value">...</div></div>
    <div class="tc-row pass-row"><div class="tc-label">Pass 判定</div><div class="tc-value">...</div></div>
  </div>
</div>

- 若已提供參數規格表，測試數值必須以表中數值為準；未涵蓋的參數才從規格書推算。
- BVA 測試誤差規範（必須嚴格遵守）：電壓類(靜態閾值)±10mV；電壓類(充放電狀態)±30mV；電流類±10mA；溫度類±1°C。
- 每張 tc-card 必須完全自含：每個 TC 的「前置條件」與「測試步驟」都必須明確列出所有需要設定的參數值，不得因為前面 TC 已設定過而省略。
- 測試點須涵蓋：下界-誤差、下界、下界+誤差、正常值、上界-誤差、上界、上界+誤差，每個測試點各一張 tc-card。
"""


def _chapter_payloads(case: Case, selected_titles: list[str]):
    """返回 (选中章节列表, [(chapter, 清洗后正文, 匹配参数), ...])。"""
    pdf_path = case.pdf_path
    all_chapters = case.chapters or []
    selected = [ch for ch in all_chapters if ch.get("title") in selected_titles]

    # 从库里的 case_params 还原参数列表：raw 即原始解析整行，键与匹配逻辑一致。
    csv_params = [p.raw for p in case.params] if case.params else []

    reader = pypdf.PdfReader(pdf_path)
    all_pages = [reader.pages[i].extract_text() or "" for i in range(len(reader.pages))]

    payloads = []
    for ch in selected:
        pages = extract_pages_for_chapter(pdf_path, ch, all_pages)
        cleaned = remove_repeated_lines(pages, all_pages)
        text = "\n".join(clean_pdf_text(p) for p in cleaned)
        text = truncate_at_sibling_chapter(text, ch["title"])
        matched = match_params_for_chapters([ch], csv_params) if csv_params else []
        payloads.append((ch, text, matched))
    return selected, payloads


def run_generation(
    db: Session,
    case: Case,
    selected_titles: list[str],
    on_event: Callable[[str, dict], None] | None = None,
) -> GenerationTask:
    """同步执行生成：分章节调模型，拼装 HTML，落库。返回完成的 task。

    on_event(event_type, data)：进度/日志/片段回调（SSE 复用）。
    """
    def emit(t: str, **data):
        if on_event:
            on_event(t, data)

    selected, payloads = _chapter_payloads(case, selected_titles)

    task = GenerationTask(
        case_id=case.id,
        selected_titles=selected_titles,
        status="running",
        total_chapters=len(selected),
        started_at=_now(),
    )
    db.add(task)
    case.status = "analyzing"
    db.commit()
    db.refresh(task)

    emit("log", msg=f"实际送入模型的章节共 {len(selected)} 个")

    html_parts: list[str] = []
    try:
        for idx, (ch, text, matched) in enumerate(payloads, start=1):
            title = ch["title"]
            task.current_chapter = title
            db.commit()
            emit("progress", current=idx, total=len(selected), chapter=title)

            prompt = build_prompt(title, text, matched)
            chunks: list[str] = []
            for piece in _llm.stream_chat(prompt):
                chunks.append(piece)
                emit("chunk", html=piece)
            chapter_html = strip_html_fences("".join(chunks))
            html_parts.append(
                f'<section class="tc-section"><h2>{title}</h2>\n{chapter_html}\n</section>'
            )

        full_html = "\n".join(html_parts)
        tc_count = full_html.count('class="tc-card"')

        result = GenerationResult(
            task_id=task.id, case_id=case.id, html=full_html, tc_count=tc_count
        )
        db.add(result)
        task.status = "done"
        task.finished_at = _now()
        case.status = "done"
        db.add(OpLog(action="generate", case_id=case.id, detail={"tc_count": tc_count, "chapters": len(selected)}))
        db.commit()
        db.refresh(task)
        emit("done", tc_count=tc_count)
        return task
    except Exception as e:
        db.rollback()
        task = db.get(GenerationTask, task.id)
        if task:
            task.status = "failed"
            task.error_msg = str(e)
            task.finished_at = _now()
        case.status = "failed"
        db.commit()
        emit("error", msg=str(e))
        raise

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
from functools import lru_cache
from pathlib import Path

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

# 提示词模板外置：可直接编辑此文件迭代，无需改代码。
_PROMPT_PATH = Path(__file__).parent / "prompts" / "testcase_prompt.txt"

# 文件缺失时的兜底模板（与文件内容等价的精简版）。
_FALLBACK_TEMPLATE = """你是资深的 BMS 固件测试工程师。请依据「{title}」章节规格与参数表生成详尽的 HTML 测试卡片。

==[{title}]==
{chapter_text}
{param_table}

要求：按 BVA 覆盖各阈值（下界-误差/下界/下界+误差/正常/上界-误差/上界/上界+误差）各一张卡片；
前置条件列全相关参数与所有相关状态/告警寄存器位初值；测试步骤写成可执行的有序步骤并指明读取的寄存器位；
预期行为分阶段（Delay 窗口内 / 超过 Delay / 配置影响）描述；Pass 判定逐位列值；
严格区分阈值与恢复值；BVA 误差：电压静态±10mV、电压充放电±30mV、电流±10mA、温度±1°C。
只输出若干 <div class="tc-card">…</div>，不要 <section>/<h2>、不要 ```html 围栏、不要任何说明文字。
固定结构：
<div class="tc-card"><div class="tc-header"><span class="tc-id">TC-01</span><span class="tc-name">名称</span></div>
<div class="tc-body">
<div class="tc-row"><div class="tc-label">前置条件</div><div class="tc-value">…</div></div>
<div class="tc-row"><div class="tc-label">测试步骤</div><div class="tc-value"><ol><li>…</li></ol></div></div>
<div class="tc-row"><div class="tc-label">预期行为</div><div class="tc-value">…</div></div>
<div class="tc-row pass-row"><div class="tc-label">Pass 判定</div><div class="tc-value">…</div></div>
</div></div>
"""


@lru_cache(maxsize=1)
def _load_template() -> str:
    """读取提示词模板，容忍非 UTF-8 编码（如 Windows 另存的 GBK），绝不因编码崩溃。"""
    try:
        raw = _PROMPT_PATH.read_bytes()
    except OSError:
        return _FALLBACK_TEMPLATE
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # 实在不行也别崩，用替换字符兜底。
    return raw.decode("utf-8", errors="replace")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_param_table(matched: list[dict]) -> str:
    if not matched:
        return "\n（本章节未匹配到参数表数据，请依据上方规格正文推算数值）\n"
    rows = [
        f"| {p.get('name','')} | {p.get('value','')} "
        f"| {p.get('unit') or '–'} | {p.get('min','–')} | {p.get('max','–')} |"
        for p in matched
    ]
    return (
        f"\n[本章节相关参数共 {len(matched)} 条，测试数值请以下表为准，"
        "注意区分阈值(Threshold)与恢复值(Recovery)/Min/Max]\n"
        "| 参数名称 | 当前值 | 单位 | Min | Max |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


def build_prompt(title: str, chapter_text: str, matched: list[dict]) -> str:
    """从外置模板生成单章节 Prompt（沿用卡片结构与 BVA 误差规范）。"""
    # 粗略输入预算保护：按 token≈2 字符估算，超限则截断章节正文。
    budget_chars = max(2000, _settings.llm_max_input_tokens * 2)
    if len(chapter_text) > budget_chars:
        chapter_text = chapter_text[:budget_chars] + "\n…（内容过长已截断）"

    param_table = _build_param_table(matched)
    template = _load_template()
    return (
        template.replace("{title}", title)
        .replace("{chapter_text}", chapter_text)
        .replace("{param_table}", param_table)
    )


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

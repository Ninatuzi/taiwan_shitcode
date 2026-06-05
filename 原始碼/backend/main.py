import os
import sys
import json
import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator

from openai import OpenAI
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


def _resolve_frontend_dist() -> Path | None:
    """回傳前端 dist 路徑，支援開發模式與 PyInstaller 打包後的路徑。"""
    # PyInstaller 打包後，env 由 launcher.py 設定
    env_path = os.environ.get("FRONTEND_DIST")
    if env_path and Path(env_path).is_dir():
        return Path(env_path)
    # 開發模式：從 backend 相對位置推算
    candidates = [
        Path(__file__).parent.parent / "frontend" / "dist",
        Path(sys.executable).parent / "frontend" / "dist",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return None

from backend.pdf_utils import extract_chapters, extract_pages_for_chapter, clean_pdf_text, remove_repeated_lines, truncate_at_sibling_chapter
from backend.csv_utils import parse_csv, match_params_for_chapters

# ── 本地 LLM 設定（OpenAI 相容介面；可用環境變數覆蓋，不必改程式碼）──
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://10.0.6.89:8080/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "DeepSeek_32B_f16")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "EMPTY")  # 本地服務通常不驗證，但 SDK 需要非空字串
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "8192"))
LLM_STRIP_THINK = os.environ.get("LLM_STRIP_THINK", "1") not in ("0", "false", "False", "")


class _ThinkStripper:
    """串流過濾器：移除推理模型（如 DeepSeek-R1 系列）輸出的 <think>...</think>
    區塊，避免推理文字被當成 HTML 直接渲染。非推理模型則原樣通過。"""

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> str:
        if not self._enabled:
            return text
        self._buf += text
        out: list[str] = []
        while self._buf:
            if not self._in_think:
                idx = self._buf.find(self._OPEN)
                if idx == -1:
                    # 保留結尾少量字元，以防 <think> 標籤被切在兩個 chunk 之間
                    keep = len(self._OPEN) - 1
                    if len(self._buf) > keep:
                        out.append(self._buf[:-keep])
                        self._buf = self._buf[-keep:]
                    break
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(self._OPEN):]
                self._in_think = True
            else:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:
                    keep = len(self._CLOSE) - 1
                    if len(self._buf) > keep:
                        self._buf = self._buf[-keep:]  # 丟棄 think 內容，僅留可能的半個結束標籤
                    break
                self._buf = self._buf[idx + len(self._CLOSE):]
                self._in_think = False
        return "".join(out)

    def flush(self) -> str:
        if not self._enabled:
            return ""
        out = "" if self._in_think else self._buf
        self._buf = ""
        return out


app = FastAPI(title="BMS FW Validation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Server-side session state（單使用者內部工具）──
_state: dict = {
    "pdf_path": None,
    "chapters": [],
    "csv_params": [],
}


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.pdf").suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(await file.read())
    tmp.close()

    try:
        chapters = extract_chapters(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(status_code=400, detail=str(e))

    if _state["pdf_path"] and os.path.exists(_state["pdf_path"]):
        os.unlink(_state["pdf_path"])

    _state["pdf_path"] = tmp.name
    _state["chapters"] = chapters
    return chapters


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.csv").suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb')
    tmp.write(await file.read())
    tmp.close()

    try:
        params, diag = parse_csv(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    _state["csv_params"] = params
    return {"count": len(params), "diag": diag}


class AnalyzeRequest(BaseModel):
    selected_titles: list[str]


async def _analysis_stream(selected_titles: list[str], request: Request | None = None) -> AsyncGenerator[str, None]:
    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    pdf_path = _state["pdf_path"]
    all_chapters = _state["chapters"]
    csv_params = _state["csv_params"]

    if not pdf_path or not os.path.exists(pdf_path):
        yield sse({"type": "error", "msg": "尚未上傳 PDF"})
        return

    selected = [ch for ch in all_chapters if ch["title"] in selected_titles]
    if not selected:
        yield sse({"type": "error", "msg": "找不到指定章節"})
        return

    yield sse({"type": "log", "msg": f"實際送入 AI 的章節（共 {len(selected)} 個）：{[ch['title'] for ch in selected]}"})

    import pypdf
    reader = pypdf.PdfReader(pdf_path)
    all_pdf_pages = [reader.pages[i].extract_text() or "" for i in range(len(reader.pages))]

    sections_text = ""
    total_matched = 0
    param_log_lines = ["── 各章節比對參數 ──"]
    total_chapters = len(selected)

    for idx, ch in enumerate(selected, start=1):
        yield sse({"type": "progress", "current": idx, "total": total_chapters, "chapter": ch["title"]})
        await asyncio.sleep(0)
        pages = extract_pages_for_chapter(pdf_path, ch, all_pdf_pages)
        cleaned = remove_repeated_lines(pages, all_pdf_pages)
        chapter_text = "\n".join(clean_pdf_text(p) for p in cleaned)
        chapter_text = truncate_at_sibling_chapter(chapter_text, ch["title"])
        sections_text += f"\n==[{ch['title']}]==\n{chapter_text}\n"

        if csv_params:
            matched = match_params_for_chapters([ch], csv_params)
            if matched:
                total_matched += len(matched)
                param_log_lines.append(f"  [{ch['title']}] {len(matched)} 筆")
                rows = [
                    f"| {p['name']} | {p['value']} "
                    f"| {p.get('unit', '–') or '–'} "
                    f"| {p.get('min', '–')} "
                    f"| {p.get('max', '–')} |"
                    for p in matched
                ]
                sections_text += (
                    f"\n[此子章節相關參數，共 {len(matched)} 筆，請以下表數值為測試依據]\n"
                    "| 參數名稱 | 目前值 | 單位 | Min | Max |\n"
                    "|---|---|---|---|---|\n"
                    + "\n".join(rows) + "\n"
                )

    raw_chars = sum(len(p) for p in all_pdf_pages)
    clean_chars = len(sections_text)
    saved_pct = (1 - clean_chars / max(raw_chars, 1)) * 100
    yield sse({"type": "log", "msg": f"清洗前 {raw_chars:,} 字符 → 清洗後 {clean_chars:,} 字符（節省 {saved_pct:.1f}%）"})

    if csv_params:
        if total_matched:
            yield sse({"type": "log", "msg": f"參數比對：共注入 {total_matched} 筆。\n" + "\n".join(param_log_lines)})
        else:
            yield sse({"type": "log", "msg": "未找到相關參數，將不注入 CSV 至 Prompt。"})

    selected_titles_list = [ch["title"] for ch in selected]
    prompt = f"""你是專業的 BMS 固件測試工程師。以下是從規格書中提取的章節內容（每個子章節後附有對應的參數規格表）：

{sections_text}

【重要限制】本次只需為以下 {len(selected_titles_list)} 個章節生成測試卡片，絕對不得額外生成其他任何章節：
{chr(10).join(f'- {t}' for t in selected_titles_list)}
若上方章節文字中出現了其他章節的標題或內容，請完全忽略，不要為那些章節生成任何內容。

請依據上述規格內容，直接輸出 HTML 測試卡片，嚴格遵守以下規則：
- 直接輸出純 HTML body 內容，不包含 <html>、<head>、<body>、<style> 標籤，不加任何說明文字、前後言、或 ```html 標記。
- 以每個子章節（==[ ]== 標記）為單位，用 <section> 包裹，並以 <h2> 標示章節名稱。
- 每個測試案例使用以下固定 HTML 結構（TC 編號在同子章節內遞增，換章節後從 01 重新開始）：

<div class="tc-card">
  <div class="tc-header">
    <span class="tc-id">TC-01</span>
    <span class="tc-name">測試名稱</span>
  </div>
  <div class="tc-body">
    <div class="tc-row"><div class="tc-label">前置條件</div><div class="tc-value">...</div></div>
    <div class="tc-row"><div class="tc-label">測試步驟</div><div class="tc-value"><ol><li>設定參數值</li><li>等待/觸發條件</li><li>讀取暫存器/旗標</li></ol></div></div>
    <div class="tc-row"><div class="tc-label">預期行為</div><div class="tc-value">...</div></div>
    <div class="tc-row pass-row"><div class="tc-label">Pass 判定</div><div class="tc-value">...</div></div>
  </div>
</div>

- 若已提供參數規格表，測試數值必須以表中數值為準；未涵蓋的參數才從規格書推算。
- BVA 測試誤差規範（必須嚴格遵守，不得自行更改）：
  * 電壓類（靜態閾值）：±10mV
  * 電壓類（充放電狀態）：±30mV
  * 電流類：±10mA
  * 溫度類：±1°C
- 每張 tc-card 必須完全自含（self-contained）：每個 TC 的「前置條件」與「測試步驟」都必須明確列出所有需要設定的參數值，不得因為前面 TC 已設定過而省略。
- 測試點須涵蓋：下界-誤差、下界、下界+誤差、正常值、上界-誤差、上界、上界+誤差，每個測試點各一張 tc-card。
"""

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    yield sse({"type": "log", "msg": f"開始呼叫本地模型 {LLM_MODEL} @ {LLM_BASE_URL} …"})

    stripper = _ThinkStripper(enabled=LLM_STRIP_THINK)
    try:
        stream = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in stream:
            if request and await request.is_disconnected():
                break
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            visible = stripper.feed(delta)
            if visible:
                yield sse({"type": "chunk", "html": visible})
                await asyncio.sleep(0)
        tail = stripper.flush()
        if tail:
            yield sse({"type": "chunk", "html": tail})
    except Exception as e:
        yield sse({"type": "error", "msg": str(e)})
        return

    yield sse({"type": "progress", "current": total_chapters, "total": total_chapters, "chapter": ""})
    yield sse({"type": "done"})


@app.post("/analyze-stream")
async def analyze_stream(req: AnalyzeRequest, request: Request):
    return StreamingResponse(
        _analysis_stream(req.selected_titles, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 靜態前端 ──（打包模式下生效，開發模式不影響）
_dist = _resolve_frontend_dist()
if _dist:
    _assets = _dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/favicon.svg")
    async def _favicon():
        return FileResponse(str(_dist / "favicon.svg"))

    @app.get("/icons.svg")
    async def _icons():
        return FileResponse(str(_dist / "icons.svg"))

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        return FileResponse(str(_dist / "index.html"))

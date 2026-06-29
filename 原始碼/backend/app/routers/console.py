"""内置测试控制台 — 一个自包含的网页,方便手动测试整条链路。

纯原生 HTML/JS,不依赖任何外部 CDN(离线可用),直接调用本服务的 /api 接口。
这不是产品前端(正式前端由他人负责),仅作开发/评测自测用。
访问: GET /
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["console"])

_PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BMS 测试用例生成 · 测试控制台</title>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,'Microsoft JhengHei','Microsoft YaHei',sans-serif;background:#eef1f5;margin:0;color:#1f2733}
header{background:#0b5fa5;color:#fff;padding:14px 22px;font-size:18px;font-weight:600}
.wrap{max-width:1080px;margin:0 auto;padding:20px}
.card{background:#fff;border:1px solid #e3e7ee;border-radius:10px;padding:16px 18px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card h3{margin:0 0 12px;font-size:15px;color:#0b5fa5}
.step-num{display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;background:#0b5fa5;color:#fff;border-radius:50%;font-size:13px;margin-right:8px}
button{background:#0b5fa5;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:14px;cursor:pointer}
button:disabled{background:#9bb6cc;cursor:not-allowed}
button.sec{background:#5a6b85}
input[type=file]{font-size:13px}
.muted{color:#6b7686;font-size:13px}
.ok{color:#137a3f}.err{color:#c0392b;white-space:pre-wrap}
#chapters{max-height:240px;overflow:auto;border:1px solid #eef1f5;border-radius:6px;padding:8px 10px;margin-top:8px}
#chapters label{display:block;padding:3px 0;font-size:14px}
.toolbar{margin:8px 0}
.toolbar a{font-size:13px;color:#0b5fa5;cursor:pointer;margin-right:14px}
.badge{display:inline-block;background:#eaf2fb;color:#0b5fa5;border-radius:6px;padding:2px 8px;font-size:12px;margin-left:6px}
/* 结果卡片样式 */
#result .tc-section>h2{font-size:16px;color:#0b5fa5;border-left:4px solid #0b5fa5;padding-left:10px;margin:18px 0 12px}
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
.spin{display:inline-block;color:#0b5fa5}
</style>
</head>
<body>
<header>BMS 测试用例生成 · 测试控制台 <span class="badge">开发自测页</span></header>
<div class="wrap">

  <div class="card">
    <h3><span class="step-num">1</span>上传规格书 PDF</h3>
    <input type="file" id="pdf" accept=".pdf">
    <button id="btnPdf" onclick="uploadPdf()">上传并解析章节</button>
    <div id="pdfMsg" class="muted"></div>
    <div id="chaptersBox" style="display:none">
      <div class="toolbar">
        <a onclick="selAll(true)">全选</a><a onclick="selAll(false)">全不选</a>
        <span class="muted" id="chCount"></span>
      </div>
      <div id="chapters"></div>
    </div>
  </div>

  <div class="card">
    <h3><span class="step-num">2</span>上传参数表 CSV（可选，但建议传，数值更准）</h3>
    <input type="file" id="csv" accept=".csv">
    <button id="btnCsv" class="sec" onclick="uploadCsv()" disabled>上传并解析参数</button>
    <div id="csvMsg" class="muted"></div>
  </div>

  <div class="card">
    <h3><span class="step-num">3</span>生成测试用例</h3>
    <button id="btnGen" onclick="generate()" disabled>对勾选的章节生成</button>
    <span class="muted">（同步生成，章节多会等较久，建议先选 1–2 个）</span>
    <div id="genMsg" class="muted"></div>
  </div>

  <div class="card">
    <h3>生成结果</h3>
    <div id="result"><span class="muted">尚无结果。</span></div>
  </div>

</div>
<script>
let caseId = null;
let chapters = [];

async function postFile(url, file){
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(url, {method:'POST', body:fd});
  const data = await r.json().catch(()=>({detail:'非 JSON 响应'}));
  if(!r.ok) throw new Error(data.detail || ('HTTP '+r.status));
  return data;
}

async function uploadPdf(){
  const f = document.getElementById('pdf').files[0];
  const msg = document.getElementById('pdfMsg');
  if(!f){ msg.innerHTML='<span class="err">请先选择 PDF 文件</span>'; return; }
  document.getElementById('btnPdf').disabled = true;
  msg.textContent = '上传解析中…';
  try{
    const d = await postFile('/api/cases/upload-pdf', f);
    caseId = d.case_id;
    chapters = d.chapters || [];
    msg.innerHTML = '<span class="ok">解析成功</span>　case_id='+caseId+'　页数='+d.pdf_page_count+'　章节数='+chapters.length;
    const box = document.getElementById('chapters');
    box.innerHTML = chapters.map((c,i)=>
      '<label><input type="checkbox" value="'+i+'"> '+escapeHtml(c.title)+'</label>').join('');
    document.getElementById('chaptersBox').style.display='block';
    document.getElementById('chCount').textContent = '共 '+chapters.length+' 个章节';
    document.getElementById('btnCsv').disabled = false;
    document.getElementById('btnGen').disabled = false;
  }catch(e){ msg.innerHTML = '<span class="err">失败：'+escapeHtml(e.message)+'</span>'; }
  document.getElementById('btnPdf').disabled = false;
}

async function uploadCsv(){
  const f = document.getElementById('csv').files[0];
  const msg = document.getElementById('csvMsg');
  if(!caseId){ msg.innerHTML='<span class="err">请先上传 PDF</span>'; return; }
  if(!f){ msg.innerHTML='<span class="err">请先选择 CSV 文件</span>'; return; }
  document.getElementById('btnCsv').disabled = true;
  msg.textContent = '上传解析中…';
  try{
    const d = await postFile('/api/cases/'+caseId+'/upload-csv', f);
    msg.innerHTML = '<span class="ok">解析成功</span>　参数条数='+d.count+'　格式='+d.csv_format;
  }catch(e){ msg.innerHTML = '<span class="err">失败：'+escapeHtml(e.message)+'</span>'; }
  document.getElementById('btnCsv').disabled = false;
}

function selAll(v){
  document.querySelectorAll('#chapters input[type=checkbox]').forEach(c=>c.checked=v);
}

async function generate(){
  const msg = document.getElementById('genMsg');
  const res = document.getElementById('result');
  if(!caseId){ msg.innerHTML='<span class="err">请先上传 PDF</span>'; return; }
  const titles = Array.from(document.querySelectorAll('#chapters input:checked'))
                      .map(c=>chapters[parseInt(c.value)].title);
  if(titles.length===0){ msg.innerHTML='<span class="err">请至少勾选一个章节</span>'; return; }
  document.getElementById('btnGen').disabled = true;
  msg.innerHTML = '<span class="spin">生成中…（正在调用本地模型，请耐心等待）</span>';
  res.innerHTML = '<span class="muted">生成中…</span>';
  try{
    const r = await fetch('/api/cases/'+caseId+'/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({selected_titles: titles})
    });
    const d = await r.json().catch(()=>({detail:'非 JSON 响应'}));
    if(!r.ok) throw new Error(d.detail || ('HTTP '+r.status));
    msg.innerHTML = '<span class="ok">完成</span>　状态='+d.status+'　章节='+d.chapters_generated+'　用例数='+d.tc_count;
    res.innerHTML = d.html || '<span class="muted">（模型未返回内容）</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">失败：'+escapeHtml(e.message)+'</span>';
    res.innerHTML = '<span class="muted">生成失败,见上方错误。</span>';
  }
  document.getElementById('btnGen').disabled = false;
}

function escapeHtml(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def console() -> str:
    return _PAGE

// 開發模式（vite dev server）走 localhost:7003；
// 生產模式（exe 打包後）由後端同時 serve 前端，使用相對路徑避免跨來源問題。
const BASE = import.meta.env.DEV ? 'http://localhost:7003' : ''

export interface Chapter {
  title: string
  page_start: number
  page_end: number
  level: number
}

export async function uploadPdf(file: File): Promise<Chapter[]> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload-pdf`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadCsv(file: File): Promise<{ count: number; diag: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload-csv`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ProgressInfo {
  current: number
  total: number
  chapter: string
}

export function streamAnalysis(
  selectedTitles: string[],
  onChunk: (html: string) => void,
  onLog: (msg: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onProgress?: (info: ProgressInfo) => void,
) {
  const ctrl = new AbortController()
  let doneCalled = false
  const safeDone = () => { if (!doneCalled) { doneCalled = true; onDone() } }

  fetch(`${BASE}/analyze-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ selected_titles: selectedTitles }),
    signal: ctrl.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) { onError(await res.text()); return }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) { safeDone(); break }
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const payload = JSON.parse(line.slice(6))
            if (payload.type === 'chunk') onChunk(payload.html)
            else if (payload.type === 'log') onLog(payload.msg)
            else if (payload.type === 'done') safeDone()
            else if (payload.type === 'error') onError(payload.msg)
            else if (payload.type === 'progress' && onProgress) {
              onProgress({ current: payload.current as number, total: payload.total as number, chapter: payload.chapter as string })
            }
          } catch {}
        }
      }
    }
  }).catch((e) => { if (e.name !== 'AbortError') onError(String(e)) })

  return () => ctrl.abort()
}

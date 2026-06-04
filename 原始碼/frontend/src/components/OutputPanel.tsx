import { useEffect, useRef } from 'react'
import { Download } from 'lucide-react'

const CARD_CSS = `
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Microsoft JhengHei', 'PingFang TC', sans-serif; background: #F8FAFC; padding: 24px; font-size: 14px; color: #1A2E3A; }
section { margin-bottom: 36px; }
h2 { font-size: 16px; font-weight: 700; padding: 10px 16px; background: #E8F6FA; border-left: 4px solid #1A9BBF; border-radius: 4px; margin-bottom: 16px; color: #0E4F6A; }
.tc-card { background: #FFFDF6; border: 1px solid #E8DCC8; border-radius: 10px; overflow: hidden; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.tc-header { background: #1A9BBF; display: flex; align-items: center; gap: 10px; padding: 10px 14px; }
.tc-id { background: rgba(255,255,255,0.22); color: #fff; font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 99px; letter-spacing: 0.5px; }
.tc-name { color: #fff; font-weight: 600; font-size: 14px; }
.tc-body { }
.tc-row { display: grid; grid-template-columns: 88px 1fr; border-top: 1px solid #F0E8D8; }
.tc-label { background: #F8F4EC; color: #7A9AAA; font-size: 12px; font-weight: 600; padding: 8px 10px; display: flex; align-items: flex-start; }
.tc-value { padding: 8px 12px; font-size: 13px; line-height: 1.6; color: #2A3A44; }
.tc-value ol { padding-left: 18px; margin: 0; }
.tc-value li { margin-bottom: 2px; }
.pass-row .tc-label { color: #2DA870; }
.pass-row .tc-value { color: #1A6A40; font-weight: 600; }
`

function exportHtml(html: string) {
  const now = new Date()
  const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`
  const fullHtml = `<!DOCTYPE html>\n<html lang="zh-TW">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>BMS FW 測試卡片</title>\n<style>${CARD_CSS}</style>\n</head>\n<body>${html}</body>\n</html>`
  const blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `BMS_TestCards_${ts}.html`
  a.click()
  URL.revokeObjectURL(url)
}

interface Props {
  html: string
  generating: boolean
  isHistoryView?: boolean
}

export default function OutputPanel({ html, generating, isHistoryView = false }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null)

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return
    const doc = iframe.contentDocument || iframe.contentWindow?.document
    if (!doc) return
    doc.open()
    doc.write(`<!DOCTYPE html><html><head><style>${CARD_CSS}</style></head><body>${html}</body></html>`)
    doc.close()
  }, [html])

  return (
    <div
      className="flex-1 flex flex-col h-screen overflow-hidden relative"
      style={{ backgroundColor: 'var(--dt-main-bg)' }}
    >
      {html ? (
        <iframe
          ref={iframeRef}
          className="w-full h-full border-0"
          title="output"
        />
      ) : (
        <div
          className="flex items-center justify-center h-full flex-col gap-3"
          style={{ color: 'var(--dt-text-muted)' }}
        >
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center"
            style={{ backgroundColor: 'rgba(0,212,255,0.07)' }}
          >
            <span className="text-3xl">📋</span>
          </div>
          <p className="text-sm">選擇章節後按下「生成測試卡片」</p>
        </div>
      )}

      {/* Top-right overlay buttons */}
      <div className="absolute top-3 right-3 flex items-center gap-2">
        {isHistoryView && (
          <div
            className="text-xs font-semibold px-3 py-1 rounded-full"
            style={{ backgroundColor: 'var(--dt-surface)', color: 'var(--dt-text-muted)', border: '1px solid var(--dt-border)' }}
          >
            歷史紀錄
          </div>
        )}
        {html && !generating && (
          <button
            onClick={() => exportHtml(html)}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1 rounded-full transition-colors"
            style={{
              backgroundColor: 'var(--dt-surface)',
              color: 'var(--dt-cyan)',
              border: '1px solid var(--dt-border)',
            }}
            title="匯出 HTML"
          >
            <Download size={12} />
            匯出 HTML
          </button>
        )}
        {generating && (
          <div
            className="text-xs font-semibold px-3 py-1 rounded-full animate-pulse"
            style={{ backgroundColor: 'var(--dt-cyan)', color: '#0F1729' }}
          >
            AI 生成中…
          </div>
        )}
      </div>
    </div>
  )
}

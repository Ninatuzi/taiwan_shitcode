import { useEffect, useRef } from 'react'
import { ChevronRight, ChevronLeft } from 'lucide-react'

interface Props {
  logs: string[]
  open: boolean
  onToggle: () => void
}

function logColor(msg: string): string {
  if (msg.startsWith('✅') || msg.includes('完成')) return 'var(--dt-success)'
  if (msg.startsWith('❌') || msg.includes('失敗') || msg.includes('錯誤')) return 'var(--dt-danger)'
  if (msg.includes('AI') || msg.includes('呼叫')) return 'var(--dt-cyan)'
  if (msg.includes('警告') || msg.includes('⚠')) return '#FFB347'
  return 'var(--dt-text-muted)'
}

export default function LogPanel({ logs, open, onToggle }: Props) {
  const logsEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, open])

  return (
    <div
      className="shrink-0 h-screen flex flex-col relative"
      style={{
        width: open ? '300px' : '40px',
        transition: 'width 0.3s ease',
        backgroundColor: 'var(--dt-sidebar-bg)',
        borderLeft: '1px solid var(--dt-border)',
      }}
    >
      {/* Toggle button */}
      <button
        onClick={onToggle}
        className="absolute top-3 flex items-center justify-center w-8 h-8 rounded-md"
        style={{
          left: open ? '8px' : '4px',
          color: 'var(--dt-text-muted)',
          backgroundColor: 'var(--dt-surface)',
          border: '1px solid var(--dt-border)',
          transition: 'left 0.3s ease',
          zIndex: 10,
        }}
        title={open ? '收起日誌' : '展開日誌'}
      >
        {open ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>

      {/* Header */}
      {open && (
        <div
          className="px-4 pt-3 pb-2 mt-12 shrink-0"
          style={{ borderBottom: '1px solid var(--dt-border)' }}
        >
          <p
            className="text-xs font-semibold uppercase tracking-wider"
            style={{ color: 'var(--dt-text-muted)' }}
          >
            系統日誌
          </p>
        </div>
      )}

      {/* Log messages */}
      {open && (
        <div className="flex-1 overflow-y-auto p-3 font-mono">
          {logs.length === 0 ? (
            <p className="text-xs" style={{ color: 'var(--dt-text-muted)' }}>
              系統訊息將顯示於此
            </p>
          ) : (
            logs.map((log, i) => (
              <p
                key={i}
                className="text-xs leading-relaxed whitespace-pre-wrap mb-0.5"
                style={{ color: logColor(log) }}
              >
                <span className="mr-2" style={{ color: 'var(--dt-text-muted)' }}>
                  [{String(i + 1).padStart(2, '0')}]
                </span>
                {log}
              </p>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      )}
    </div>
  )
}

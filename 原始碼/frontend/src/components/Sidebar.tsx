import { useRef, useState } from 'react'
import { FileText, Table2, ChevronRight, ChevronDown, Cpu, Search, X, Sun, Moon, History, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Chapter } from '@/api/client'
import type { ProgressInfo } from '@/api/client'
import type { HistoryRecord } from '@/lib/history'
import { formatHistoryDate } from '@/lib/history'

interface Props {
  chapters: Chapter[]
  checkedTitles: Set<string>
  onCheck: (title: string, checked: boolean) => void
  onPdfSelect: (file: File) => void
  onCsvSelect: (file: File) => void
  onGenerate: () => void
  onAbort: () => void
  generating: boolean
  pdfName: string | null
  csvName: string | null
  csvCount: number | null
  progress: ProgressInfo | null
  onSelectAll: () => void
  onDeselectAll: () => void
  theme: 'dark' | 'light'
  onThemeToggle: () => void
  history: HistoryRecord[]
  onHistorySelect: (record: HistoryRecord) => void
  onHistoryDelete: (id: string) => void
}

interface TreeNode {
  chapter: Chapter
  children: TreeNode[]
}

function buildTree(chapters: Chapter[]): TreeNode[] {
  const roots: TreeNode[] = []
  const stack: TreeNode[] = []
  for (const ch of chapters) {
    const node: TreeNode = { chapter: ch, children: [] }
    while (stack.length > 0 && stack[stack.length - 1].chapter.level >= ch.level) stack.pop()
    if (stack.length === 0) roots.push(node)
    else stack[stack.length - 1].children.push(node)
    stack.push(node)
  }
  return roots
}

function TreeItem({
  node, checkedTitles, onCheck, depth, forceOpen = false,
}: { node: TreeNode; checkedTitles: Set<string>; onCheck: (t: string, c: boolean) => void; depth: number; forceOpen?: boolean }) {
  const [open, setOpen] = useState(depth < 1)
  const hasChildren = node.children.length > 0
  const checked = checkedTitles.has(node.chapter.title)
  const isOpen = forceOpen || open

  return (
    <div>
      <div
        className={cn('flex items-center gap-1 px-2 py-1 rounded-md cursor-pointer select-none transition-colors')}
        style={{
          paddingLeft: `${8 + depth * 16}px`,
          backgroundColor: checked ? 'rgba(0,212,255,0.1)' : undefined,
        }}
        onMouseEnter={e => { if (!checked) (e.currentTarget as HTMLElement).style.backgroundColor = 'rgba(255,255,255,0.04)' }}
        onMouseLeave={e => { if (!checked) (e.currentTarget as HTMLElement).style.backgroundColor = '' }}
      >
        <button
          className="w-4 h-4 flex items-center justify-center shrink-0"
          style={{ color: 'var(--dt-text-muted)' }}
          onClick={() => hasChildren && setOpen(o => !o)}
        >
          {hasChildren
            ? isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />
            : <span className="w-4" />}
        </button>
        <input
          type="checkbox"
          checked={checked}
          onChange={e => onCheck(node.chapter.title, e.target.checked)}
          className="shrink-0"
          style={{ accentColor: 'var(--dt-cyan)' }}
        />
        <span
          className={cn('text-sm leading-snug flex-1', depth === 0 && 'font-semibold')}
          style={{ color: checked ? 'var(--dt-cyan)' : depth === 0 ? 'var(--dt-text-primary)' : 'var(--dt-text-muted)' }}
          onClick={() => onCheck(node.chapter.title, !checked)}
        >
          {node.chapter.title}
        </span>
      </div>
      {hasChildren && isOpen && (
        <div>
          {node.children.map(child => (
            <TreeItem key={child.chapter.title} node={child} checkedTitles={checkedTitles} onCheck={onCheck} depth={depth + 1} forceOpen={forceOpen} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function Sidebar({
  chapters, checkedTitles, onCheck, onPdfSelect, onCsvSelect,
  onGenerate, onAbort, generating, pdfName, csvName, csvCount,
  progress, onSelectAll, onDeselectAll, theme, onThemeToggle,
  history, onHistorySelect, onHistoryDelete,
}: Props) {
  const pdfRef = useRef<HTMLInputElement>(null)
  const csvRef = useRef<HTMLInputElement>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [mode, setMode] = useState<'normal' | 'history'>('normal')
  const selectedCount = checkedTitles.size

  const filteredChapters = searchQuery
    ? chapters.filter(ch => {
        const q = searchQuery.toLowerCase()
        if (ch.title.toLowerCase().includes(q)) return true
        const idx = chapters.indexOf(ch)
        for (let i = idx + 1; i < chapters.length; i++) {
          if (chapters[i].level <= ch.level) break
          if (chapters[i].title.toLowerCase().includes(q)) return true
        }
        return false
      })
    : chapters
  const tree = buildTree(filteredChapters)

  return (
    <aside
      className="shrink-0 h-screen flex flex-col overflow-hidden"
      style={{
        width: '260px',
        backgroundColor: 'var(--dt-sidebar-bg)',
        borderRight: '1px solid var(--dt-border)',
      }}
    >
      {/* Logo */}
      <div
        className="px-4 py-4 flex items-center gap-2 shrink-0"
        style={{ borderBottom: '1px solid var(--dt-border)' }}
      >
        <Cpu size={20} style={{ color: 'var(--dt-cyan)' }} />
        <span className="font-bold text-sm tracking-wide flex-1" style={{ color: 'var(--dt-text-primary)' }}>
          BMS FW Validation
        </span>
        <button
          onClick={() => setMode(m => m === 'history' ? 'normal' : 'history')}
          className="w-7 h-7 flex items-center justify-center rounded-md transition-colors"
          style={{
            color: mode === 'history' ? 'var(--dt-cyan)' : 'var(--dt-text-muted)',
            backgroundColor: mode === 'history' ? 'rgba(0,212,255,0.1)' : 'var(--dt-surface)',
            border: `1px solid ${mode === 'history' ? 'var(--dt-cyan)' : 'var(--dt-border)'}`,
          }}
          title="歷史紀錄"
        >
          <History size={13} />
        </button>
        <button
          onClick={onThemeToggle}
          className="w-7 h-7 flex items-center justify-center rounded-md transition-colors"
          style={{ color: 'var(--dt-text-muted)', backgroundColor: 'var(--dt-surface)', border: '1px solid var(--dt-border)' }}
          title={theme === 'dark' ? '切換淺色模式' : '切換深色模式'}
        >
          {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
        </button>
      </div>

      {/* History panel */}
      {mode === 'history' && (
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
            {history.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2" style={{ color: 'var(--dt-text-muted)' }}>
                <History size={28} />
                <p className="text-xs text-center">尚無歷史紀錄<br/>生成完成後自動儲存</p>
              </div>
            ) : (
              history.map(record => (
                <div
                  key={record.id}
                  className="rounded-lg p-3 cursor-pointer group"
                  style={{ backgroundColor: 'var(--dt-surface)', border: '1px solid var(--dt-border)' }}
                  onClick={() => { onHistorySelect(record); setMode('normal') }}
                >
                  <div className="flex items-start justify-between gap-1">
                    <span className="text-xs font-semibold truncate flex-1" style={{ color: 'var(--dt-text-primary)' }}>
                      {record.pdfName || '未命名'}
                    </span>
                    <button
                      onClick={e => { e.stopPropagation(); onHistoryDelete(record.id) }}
                      className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      style={{ color: 'var(--dt-danger)' }}
                      title="刪除"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--dt-text-muted)' }}>
                    {formatHistoryDate(record.createdAt)} · {record.chapters.length} 個章節
                  </p>
                  <p className="text-xs mt-1 truncate" style={{ color: 'var(--dt-text-muted)' }}>
                    {record.chapters.slice(0, 2).join('、')}{record.chapters.length > 2 ? '…' : ''}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {mode === 'normal' && <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1 p-3">
        {/* PDF */}
        <section>
          <p
            className="text-xs font-semibold uppercase tracking-wider px-1 mb-1"
            style={{ color: 'var(--dt-text-muted)' }}
          >
            規格書
          </p>
          <input
            ref={pdfRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={e => e.target.files?.[0] && onPdfSelect(e.target.files[0])}
          />
          <button
            onClick={() => pdfRef.current?.click()}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors"
            style={{
              backgroundColor: 'var(--dt-surface)',
              border: `1px solid ${pdfName ? 'var(--dt-cyan)' : 'var(--dt-border)'}`,
              color: pdfName ? 'var(--dt-cyan)' : 'var(--dt-text-muted)',
            }}
          >
            <FileText size={15} className="shrink-0" />
            <span className="truncate text-left">{pdfName ?? '選擇 PDF 規格書'}</span>
          </button>
        </section>

        {/* CSV */}
        <section className="mt-2">
          <p
            className="text-xs font-semibold uppercase tracking-wider px-1 mb-1"
            style={{ color: 'var(--dt-text-muted)' }}
          >
            參數檔（可選）
          </p>
          <input
            ref={csvRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={e => e.target.files?.[0] && onCsvSelect(e.target.files[0])}
          />
          <button
            onClick={() => csvRef.current?.click()}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors"
            style={{
              backgroundColor: 'var(--dt-surface)',
              border: `1px solid ${csvName ? 'var(--dt-success)' : 'var(--dt-border)'}`,
              color: csvName ? 'var(--dt-success)' : 'var(--dt-text-muted)',
            }}
          >
            <Table2 size={15} className="shrink-0" />
            <span className="truncate text-left">
              {csvName ? `${csvName}${csvCount != null ? `（${csvCount} 筆）` : ''}` : '選擇 CSV 參數檔'}
            </span>
          </button>
        </section>

        {/* Chapter Tree */}
        {chapters.length > 0 && (
          <section className="mt-3 flex flex-col min-h-0">
            <div className="flex items-center justify-between px-1 mb-1">
              <p
                className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: 'var(--dt-text-muted)' }}
              >
                章節選擇
              </p>
              <div className="flex items-center gap-1">
                {selectedCount > 0 && (
                  <span
                    className="text-xs rounded-full px-2 py-0.5"
                    style={{ backgroundColor: 'rgba(0,212,255,0.15)', color: 'var(--dt-cyan)' }}
                  >
                    {selectedCount} 已選
                  </span>
                )}
                <button
                  onClick={onSelectAll}
                  className="text-xs px-1.5 py-0.5 rounded transition-colors hover:opacity-80"
                  style={{ color: 'var(--dt-text-muted)' }}
                  title="全選"
                >
                  全選
                </button>
                <span style={{ color: 'var(--dt-border)' }}>|</span>
                <button
                  onClick={onDeselectAll}
                  className="text-xs px-1.5 py-0.5 rounded transition-colors hover:opacity-80"
                  style={{ color: 'var(--dt-text-muted)' }}
                  title="取消全選"
                >
                  取消
                </button>
              </div>
            </div>
            <div className="relative mb-1">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: 'var(--dt-text-muted)' }} />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="搜尋章節…"
                className="w-full text-xs rounded-md pl-7 pr-7 py-1.5 outline-none"
                style={{
                  backgroundColor: 'var(--dt-surface)',
                  border: '1px solid var(--dt-border)',
                  color: 'var(--dt-text-primary)',
                }}
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2"
                  style={{ color: 'var(--dt-text-muted)' }}
                >
                  <X size={13} />
                </button>
              )}
            </div>
            <div
              className="overflow-y-auto overflow-x-hidden rounded-lg py-1"
              style={{
                backgroundColor: 'var(--dt-surface)',
                border: '1px solid var(--dt-border)',
                maxHeight: 'calc(100vh - 320px)',
              }}
            >
              {tree.map(node => (
                <TreeItem key={node.chapter.title} node={node} checkedTitles={checkedTitles} onCheck={onCheck} depth={0} forceOpen={!!searchQuery} />
              ))}
            </div>
          </section>
        )}
      </div>}

      {/* Generate Button */}
      <div className="p-3 shrink-0" style={{ borderTop: '1px solid var(--dt-border)' }}>
        {generating && progress && (
          <div
            className="mb-2 px-3 py-2 rounded-lg text-xs"
            style={{
              backgroundColor: 'var(--dt-surface)',
              border: '1px solid var(--dt-border)',
            }}
          >
            <p style={{ color: 'var(--dt-text-muted)' }}>正在處理</p>
            <p className="font-semibold mt-0.5 truncate" style={{ color: 'var(--dt-cyan)' }}>
              {progress.current} / {progress.total} — {progress.chapter || '準備輸出…'}
            </p>
          </div>
        )}
        {generating ? (
          <button
            onClick={onAbort}
            className="w-full py-2 px-4 rounded-md text-sm font-semibold transition-all"
            style={{
              backgroundColor: 'var(--dt-surface)',
              color: 'var(--dt-danger)',
              border: '1px solid var(--dt-danger)',
              cursor: 'pointer',
            }}
          >
            ⏹ 停止生成
          </button>
        ) : (
          <button
            onClick={onGenerate}
            disabled={selectedCount === 0}
            className="w-full py-2 px-4 rounded-md text-sm font-semibold transition-all"
            style={{
              backgroundColor: selectedCount === 0 ? 'var(--dt-surface)' : 'var(--dt-cyan)',
              color: selectedCount === 0 ? 'var(--dt-text-muted)' : theme === 'light' ? '#FFFFFF' : '#0F1729',
              cursor: selectedCount === 0 ? 'not-allowed' : 'pointer',
              opacity: selectedCount === 0 ? 0.5 : 1,
              border: '1px solid var(--dt-border)',
            }}
          >
            {`生成測試卡片${selectedCount > 0 ? `（${selectedCount} 章節）` : ''}`}
          </button>
        )}
      </div>
    </aside>
  )
}

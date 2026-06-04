import { useState, useCallback, useRef, useEffect } from 'react'
import Sidebar from '@/components/Sidebar'
import OutputPanel from '@/components/OutputPanel'
import LogPanel from '@/components/LogPanel'
import { uploadPdf, uploadCsv, streamAnalysis } from '@/api/client'
import type { Chapter, ProgressInfo } from '@/api/client'
import { loadHistory, addHistoryRecord, deleteHistoryRecord } from '@/lib/history'
import type { HistoryRecord } from '@/lib/history'
import './index.css'

export default function App() {
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [checkedTitles, setCheckedTitles] = useState<Set<string>>(new Set())
  const [pdfName, setPdfName] = useState<string | null>(null)
  const [csvName, setCsvName] = useState<string | null>(null)
  const [csvCount, setCsvCount] = useState<number | null>(null)
  const [html, setHtml] = useState('')
  const [generating, setGenerating] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [progress, setProgress] = useState<ProgressInfo | null>(null)
  const [logPanelOpen, setLogPanelOpen] = useState(false)
  const abortRef = useRef<(() => void) | null>(null)
  const [history, setHistory] = useState<HistoryRecord[]>(() => loadHistory())
  const [historyHtml, setHistoryHtml] = useState('')
  const [isHistoryView, setIsHistoryView] = useState(false)
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    (localStorage.getItem('bms-theme') as 'dark' | 'light') ?? 'dark'
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme === 'light' ? 'light' : ''
    localStorage.setItem('bms-theme', theme)
  }, [theme])

  const handleThemeToggle = useCallback(() => {
    setTheme(t => t === 'dark' ? 'light' : 'dark')
  }, [])

  const addLog = (msg: string) => setLogs(prev => [...prev, msg])

  const handlePdfSelect = useCallback(async (file: File) => {
    setPdfName(file.name)
    addLog(`載入 PDF：${file.name}`)
    try {
      const chs = await uploadPdf(file)
      setChapters(chs)
      setCheckedTitles(new Set())
      addLog(`章節解析完成，共 ${chs.length} 個章節。`)
    } catch (e) {
      addLog(`❌ PDF 解析失敗：${e}`)
    }
  }, [])

  const handleCsvSelect = useCallback(async (file: File) => {
    setCsvName(file.name)
    addLog(`載入 CSV：${file.name}`)
    try {
      const res = await uploadCsv(file)
      setCsvCount(res.count)
      addLog(res.diag)
    } catch (e) {
      addLog(`❌ CSV 解析失敗：${e}`)
    }
  }, [])

  const handleCheck = useCallback((title: string, checked: boolean) => {
    setCheckedTitles(prev => {
      const next = new Set(prev)
      if (checked) next.add(title)
      else next.delete(title)
      return next
    })
  }, [])

  const handleSelectAll = useCallback(() => {
    setCheckedTitles(new Set(chapters.map(ch => ch.title)))
  }, [chapters])

  const handleDeselectAll = useCallback(() => {
    setCheckedTitles(new Set())
  }, [])

  const handleHistorySelect = useCallback((record: HistoryRecord) => {
    setHistoryHtml(record.html)
    setIsHistoryView(true)
  }, [])

  const handleHistoryDelete = useCallback((id: string) => {
    setHistory(deleteHistoryRecord(id))
  }, [])

  const handleGenerate = useCallback(() => {
    if (checkedTitles.size === 0) return
    setGenerating(true)
    setHtml('')
    setLogs([])
    setProgress(null)
    setLogPanelOpen(true)
    setIsHistoryView(false)
    addLog(`開始生成，已選章節：${[...checkedTitles].join('、')}`)

    const currentPdfName = pdfName ?? ''
    const currentChapters = [...checkedTitles]
    let accumulated = ''
    abortRef.current = streamAnalysis(
      currentChapters,
      (chunk) => { accumulated += chunk; setHtml(accumulated) },
      (msg) => addLog(msg),
      () => {
        setGenerating(false); setProgress(null); abortRef.current = null
        addLog('✅ 生成完成。')
        setHistory(addHistoryRecord({ pdfName: currentPdfName, chapters: currentChapters, html: accumulated }))
      },
      (err) => { setGenerating(false); setProgress(null); abortRef.current = null; addLog(`❌ 錯誤：${err}`) },
      (info) => setProgress(info),
    )
  }, [checkedTitles, pdfName])

  const handleAbort = useCallback(() => {
    abortRef.current?.()
    abortRef.current = null
    setGenerating(false)
    setProgress(null)
    addLog('⏹ 已中止生成。')
  }, [])

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        chapters={chapters}
        checkedTitles={checkedTitles}
        onCheck={handleCheck}
        onPdfSelect={handlePdfSelect}
        onCsvSelect={handleCsvSelect}
        onGenerate={handleGenerate}
        onAbort={handleAbort}
        generating={generating}
        theme={theme}
        onThemeToggle={handleThemeToggle}
        pdfName={pdfName}
        csvName={csvName}
        csvCount={csvCount}
        progress={progress}
        onSelectAll={handleSelectAll}
        onDeselectAll={handleDeselectAll}
        history={history}
        onHistorySelect={handleHistorySelect}
        onHistoryDelete={handleHistoryDelete}
      />
      <OutputPanel
        html={isHistoryView ? historyHtml : html}
        generating={generating}
        isHistoryView={isHistoryView}
      />
      <LogPanel
        logs={logs}
        open={logPanelOpen}
        onToggle={() => setLogPanelOpen(o => !o)}
      />
    </div>
  )
}

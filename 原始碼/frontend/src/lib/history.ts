export interface HistoryRecord {
  id: string
  createdAt: string
  pdfName: string
  chapters: string[]
  html: string
}

const KEY = 'bms-history'
const MAX_RECORDS = 20
const MAX_BYTES = 4 * 1024 * 1024 // 4MB

export function loadHistory(): HistoryRecord[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '[]')
  } catch {
    return []
  }
}

function saveHistory(records: HistoryRecord[]): void {
  localStorage.setItem(KEY, JSON.stringify(records))
}

export function addHistoryRecord(record: Omit<HistoryRecord, 'id' | 'createdAt'>): HistoryRecord[] {
  const newRecord: HistoryRecord = {
    id: Date.now().toString(),
    createdAt: new Date().toISOString(),
    ...record,
  }
  let records = [newRecord, ...loadHistory()]
  if (records.length > MAX_RECORDS) records = records.slice(0, MAX_RECORDS)
  // trim if over size limit (remove oldest)
  while (records.length > 1 && new Blob([JSON.stringify(records)]).size > MAX_BYTES) {
    records = records.slice(0, -1)
  }
  saveHistory(records)
  return records
}

export function deleteHistoryRecord(id: string): HistoryRecord[] {
  const records = loadHistory().filter(r => r.id !== id)
  saveHistory(records)
  return records
}

export function formatHistoryDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

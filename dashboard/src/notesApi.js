/**
 * Notes API — supports both fetch (PostgreSQL) and localStorage (test mode).
 * Test mode: ?test=1 in URL or VITE_TEST_MODE=1 env.
 */
const API_BASE = '/api'
const STORAGE_KEYS = {
  boards: 'notes_test_boards',
  items: 'notes_test_items',
  finished: 'notes_test_finished',
  archived: 'notes_test_archived',
  boardSettings: 'notes_board_settings',
}

export function isTestMode() {
  if (typeof window === 'undefined') return false
  const url = new URL(window.location.href)
  if (url.searchParams.get('test') === '1') return true
  const env = import.meta.env?.VITE_TEST_MODE
  return env === 'true' || env === '1' || env === true
}

// --- localStorage helpers ---
function getStorage(key, defaultVal = null) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : defaultVal
  } catch {
    return defaultVal
  }
}

function setStorage(key, val) {
  try {
    localStorage.setItem(key, JSON.stringify(val))
  } catch (e) {
    console.warn('notesApi: localStorage set failed', e)
  }
}

let _nextId = 1
function nextId(existing) {
  const max = existing?.reduce((m, x) => Math.max(m, x.id || 0), 0) ?? 0
  _nextId = Math.max(_nextId, max + 1)
  return _nextId
}

// --- localStorage API ---
async function storageGetBoards() {
  let boards = getStorage(STORAGE_KEYS.boards, [])
  if (boards.length === 0) {
    boards = [{ id: 1, name: 'General', sort_order: 0, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }]
    setStorage(STORAGE_KEYS.boards, boards)
  }
  return { boards }
}

async function storageGetItems(boardId) {
  const all = getStorage(STORAGE_KEYS.items, [])
  const items = all.filter((i) => i.board_id === boardId)
  return { items }
}

async function storageCreateItem(boardId, body) {
  const all = getStorage(STORAGE_KEYS.items, [])
  const id = nextId(all)
  const item = {
    id,
    board_id: boardId,
    item_type: body.item_type,
    content: body.content ?? (body.item_type === 'note' ? { html: '', title: '' } : { items: [], title: '' }),
    position: body.position ?? { x: 0, y: 0 },
    size: body.size ?? { width: 200, height: 180 },
    background_color: body.background_color ?? '#fef08a',
    header_color: body.header_color ?? '#eab308',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
  all.push(item)
  setStorage(STORAGE_KEYS.items, all)
  return item
}

async function storageUpdateItem(itemId, patch) {
  const all = getStorage(STORAGE_KEYS.items, [])
  const idx = all.findIndex((i) => i.id === itemId)
  if (idx < 0) throw new Error('Item not found')
  all[idx] = { ...all[idx], ...patch, updated_at: new Date().toISOString() }
  setStorage(STORAGE_KEYS.items, all)
  return all[idx]
}

async function storageDeleteItem(itemId) {
  const all = getStorage(STORAGE_KEYS.items, [])
  const filtered = all.filter((i) => i.id !== itemId)
  if (filtered.length === all.length) throw new Error('Item not found')
  setStorage(STORAGE_KEYS.items, filtered)
  return { success: true }
}

async function storageCreateBoard(body) {
  const boards = getStorage(STORAGE_KEYS.boards, [])
  const id = nextId(boards)
  const board = {
    id,
    name: body.name ?? 'New board',
    sort_order: boards.length,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
  boards.push(board)
  setStorage(STORAGE_KEYS.boards, boards)
  return board
}

async function storageUpdateBoard(boardId, body) {
  const boards = getStorage(STORAGE_KEYS.boards, [])
  const idx = boards.findIndex((b) => b.id === boardId)
  if (idx < 0) throw new Error('Board not found')
  boards[idx] = { ...boards[idx], name: body.name ?? boards[idx].name, updated_at: new Date().toISOString() }
  setStorage(STORAGE_KEYS.boards, boards)
  return boards[idx]
}

async function storageDeleteBoard(boardId) {
  const boards = getStorage(STORAGE_KEYS.boards, [])
  const items = getStorage(STORAGE_KEYS.items, [])
  const finished = getStorage(STORAGE_KEYS.finished, {})
  const filtered = boards.filter((b) => b.id !== boardId)
  if (filtered.length === boards.length) throw new Error('Board not found')
  setStorage(STORAGE_KEYS.boards, filtered)
  setStorage(STORAGE_KEYS.items, items.filter((i) => i.board_id !== boardId))
  const newFinished = { ...finished }
  delete newFinished[boardId]
  setStorage(STORAGE_KEYS.finished, newFinished)
  return { success: true }
}

// Finished items (per board)
export async function getFinishedItems(boardId) {
  if (isTestMode()) {
    const finished = getStorage(STORAGE_KEYS.finished, {})
    return finished[boardId] ?? []
  }
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/finished`)
  if (!res.ok) throw new Error('Failed to load finished items')
  const data = await res.json()
  return data.items ?? []
}

export async function addFinishedItem(boardId, item) {
  if (isTestMode()) {
    const finished = getStorage(STORAGE_KEYS.finished, {})
    const list = finished[boardId] ?? []
    const id = `f-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const entry = {
      id,
      text: item.text,
      finished_at: new Date().toISOString(),
      source_checklist_id: item.source_checklist_id,
    }
    list.push(entry)
    finished[boardId] = list
    setStorage(STORAGE_KEYS.finished, finished)
    return entry
  }
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/finished`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(item),
  })
  if (!res.ok) throw new Error('Failed to add finished item')
  return res.json()
}

export async function archiveFinishedItem(boardId, finishedId) {
  if (isTestMode()) {
    const finished = getStorage(STORAGE_KEYS.finished, {})
    const archived = getStorage(STORAGE_KEYS.archived, [])
    const list = finished[boardId] ?? []
    const idx = list.findIndex((f) => f.id === finishedId)
    if (idx < 0) throw new Error('Finished item not found')
    const [entry] = list.splice(idx, 1)
    archived.push({
      ...entry,
      archived_at: new Date().toISOString(),
      board_id: boardId,
    })
    finished[boardId] = list
    setStorage(STORAGE_KEYS.finished, finished)
    setStorage(STORAGE_KEYS.archived, archived)
    return { success: true }
  }
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/finished/${finishedId}/archive`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Failed to archive')
  return res.json()
}

// Main API
export async function getBoards() {
  if (isTestMode()) return storageGetBoards()
  const res = await fetch(`${API_BASE}/notes/boards`)
  if (!res.ok) throw new Error('Failed to load boards')
  return res.json()
}

export async function getItems(boardId) {
  if (isTestMode()) return storageGetItems(boardId)
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/items`)
  if (!res.ok) throw new Error('Failed to load items')
  return res.json()
}

export async function createItem(boardId, body) {
  if (isTestMode()) return storageCreateItem(boardId, body)
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/items`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Failed to create item')
  return res.json()
}

export async function updateItem(itemId, patch) {
  if (isTestMode()) return storageUpdateItem(itemId, patch)
  const res = await fetch(`${API_BASE}/notes/items/${itemId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error('Failed to update')
  return res.json()
}

export async function deleteItem(itemId) {
  if (isTestMode()) return storageDeleteItem(itemId)
  const res = await fetch(`${API_BASE}/notes/items/${itemId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete')
  return res.json()
}

export async function createBoard(body) {
  if (isTestMode()) return storageCreateBoard(body)
  const res = await fetch(`${API_BASE}/notes/boards`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Failed to create board')
  return res.json()
}

export async function updateBoard(boardId, body) {
  if (isTestMode()) return storageUpdateBoard(boardId, body)
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Failed to update board')
  return res.json()
}

// Board appearance (grid, background) — stored in localStorage for all modes
const DEFAULT_BOARD_SETTINGS = {
  gridEnabled: true,
  gridSize: 24,
  backgroundColor: '#1e293b',
}

export function getBoardSettings(boardId) {
  if (boardId == null) return { ...DEFAULT_BOARD_SETTINGS }
  const all = getStorage(STORAGE_KEYS.boardSettings, {})
  return { ...DEFAULT_BOARD_SETTINGS, ...all[String(boardId)] }
}

export function setBoardSettings(boardId, settings) {
  if (boardId == null) return
  const all = getStorage(STORAGE_KEYS.boardSettings, {})
  const key = String(boardId)
  all[key] = { ...all[key], ...settings }
  setStorage(STORAGE_KEYS.boardSettings, all)
}

export const BOARD_PRESETS = {
  cream: [
    { name: 'Cream', color: '#f5f0e6' },
    { name: 'Warm', color: '#faf6ed' },
    { name: 'Sand', color: '#f0e6d8' },
  ],
  bold: [
    { name: 'Slate', color: '#2d3748' },
    { name: 'Navy', color: '#1a365d' },
    { name: 'Charcoal', color: '#4a5568' },
  ],
  darkMode: [
    { name: 'Slate 900', color: '#1e293b' },
    { name: 'Slate 950', color: '#0f172a' },
    { name: 'Slate 800', color: '#334155' },
  ],
  lightMode: [
    { name: 'Snow', color: '#f8fafc' },
    { name: 'Cloud', color: '#f1f5f9' },
    { name: 'Mist', color: '#e2e8f0' },
  ],
  pastel: [
    { name: 'Lemon', color: '#fef3c7' },
    { name: 'Sky', color: '#dbeafe' },
    { name: 'Mint', color: '#d1fae5' },
    { name: 'Blush', color: '#fce7f3' },
  ],
}

export async function deleteBoard(boardId) {
  if (isTestMode()) return storageDeleteBoard(boardId)
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete board')
  return res.json()
}

// AI features (require backend — not available in test mode)
export async function summarizeBoard(boardId) {
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/summarize`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to summarize')
  return res.json()
}

export async function organizeBoard(boardId) {
  const res = await fetch(`${API_BASE}/notes/boards/${boardId}/organize`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to organize')
  return res.json()
}

export async function hindsightRecall(query) {
  const res = await fetch(`${API_BASE}/notes/hindsight-recall`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })
  if (!res.ok) throw new Error('Failed to recall')
  return res.json()
}

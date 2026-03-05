import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'

const API_BASE = '/api'

const ENTRY_TYPE_META = {
  wonder:     { icon: '🌙', label: 'Wonder',     color: 'text-indigo-300',  bg: 'bg-indigo-900/30',  border: 'border-indigo-700/40' },
  reflection: { icon: '🪞', label: 'Reflection', color: 'text-purple-300',  bg: 'bg-purple-900/30',  border: 'border-purple-700/40' },
  research:   { icon: '🔬', label: 'Research',   color: 'text-cyan-300',    bg: 'bg-cyan-900/30',    border: 'border-cyan-700/40'   },
  summary:    { icon: '📓', label: 'Summary',    color: 'text-emerald-300', bg: 'bg-emerald-900/30', border: 'border-emerald-700/40'},
  heartbeat:  { icon: '💓', label: 'Heartbeat',  color: 'text-rose-300',    bg: 'bg-rose-900/30',    border: 'border-rose-700/40'   },
  user_note:  { icon: '✏️', label: 'Your Note',  color: 'text-amber-300',   bg: 'bg-amber-900/30',   border: 'border-amber-700/40'  },
  chat:       { icon: '💬', label: 'Chat',       color: 'text-slate-300',   bg: 'bg-slate-800/60',   border: 'border-slate-700/40'  },
}

const FILTER_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'user_note', label: 'User notes' },
  { value: 'reflection', label: 'AI reflections' },
  { value: 'cron', label: 'AI cron jobs' },
  { value: 'heartbeat', label: 'AI heartbeats' },
]

function entryMatchesFilter(entry, filter) {
  if (filter === 'all') return true
  if (filter === 'user_note') return entry.entry_type === 'user_note'
  if (filter === 'reflection') return entry.entry_type === 'reflection'
  if (filter === 'cron') return entry.source === 'heartbeat'
  if (filter === 'heartbeat') return entry.entry_type === 'heartbeat'
  return true
}

function formatTime(isoStr) {
  if (!isoStr) return ''
  try {
    return new Date(isoStr).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
  } catch { return '' }
}

function formatDayHeading(dateStr) {
  try {
    // Parse as local date to avoid timezone shift
    const [y, m, d] = dateStr.split('-').map(Number)
    const date = new Date(y, m - 1, d)
    return date.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
  } catch { return dateStr }
}

function formatMonthLabel(ym) {
  try {
    const [y, m] = ym.split('-').map(Number)
    return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  } catch { return ym }
}

function prevMonth(ym) {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 2, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function nextMonth(ym) {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function currentYearMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

// ── Entry card ────────────────────────────────────────────────────────────────

function EntryCard({ entry, onDelete, onUpdated }) {
  const [expanded, setExpanded] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [editTitle, setEditTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const meta = ENTRY_TYPE_META[entry.entry_type] || ENTRY_TYPE_META.heartbeat

  const startEdit = () => {
    setEditText(entry.content || '')
    setEditTitle(entry.title || '')
    setEditing(true)
    setExpanded(true)
  }

  const saveEdit = async () => {
    if (!editText.trim()) return
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/journal/entries/${entry.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
        content: editText.trim(),
        title: editTitle.trim(),
        append: false,
      }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
      setEditing(false)
      onUpdated?.()
    } catch (e) {
      console.error('Update failed', e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`rounded-xl border ${meta.border} ${meta.bg} overflow-hidden`}>
      {/* Header row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:brightness-110 transition-all select-none"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="text-lg shrink-0">{meta.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-sm font-medium ${meta.color}`}>
              {entry.title || meta.label}
            </span>
            {entry.entry_type === 'user_note' && (
              <span className="text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-700/40 text-amber-200">
                User
              </span>
            )}
            <span className="text-xs text-slate-500">
              {meta.label !== (entry.title || meta.label) ? `· ${meta.label}` : ''}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-500">
            <span>{formatTime(entry.created_at)}</span>
            <span>·</span>
            <span>{entry.word_count.toLocaleString()} words</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {entry.entry_type === 'user_note' && !confirmDelete && (
            <>
              <button
                onClick={e => { e.stopPropagation(); startEdit() }}
                className="text-xs text-slate-500 hover:text-amber-400 px-2 py-1 rounded transition-colors"
              >
                Edit
              </button>
              <button
                onClick={e => { e.stopPropagation(); setConfirmDelete(true) }}
                className="text-xs text-slate-500 hover:text-red-400 px-2 py-1 rounded transition-colors"
              >
                Delete
              </button>
            </>
          )}
          {confirmDelete && (
            <>
              <button
                onClick={e => { e.stopPropagation(); onDelete(entry.id) }}
                className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded transition-colors"
              >
                Confirm
              </button>
              <button
                onClick={e => { e.stopPropagation(); setConfirmDelete(false) }}
                className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded transition-colors"
              >
                Cancel
              </button>
            </>
          )}
          <span className={`text-slate-400 text-sm transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-white/5">
          {editing ? (
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Title</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  placeholder="Title (optional)"
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Content</label>
                <textarea
                  value={editText}
                  onChange={e => setEditText(e.target.value)}
                  placeholder="Write your note..."
                  rows={6}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 resize-none"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => { setEditing(false); setEditText(''); setEditTitle('') }}
                  className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded"
                >
                  Cancel
                </button>
                <button
                  onClick={saveEdit}
                  disabled={saving || !editText.trim()}
                  className="text-xs bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none text-slate-200
              [&_p]:my-1.5 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5
              [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5
              [&_li]:my-0.5 [&_strong]:font-semibold [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm">
              <ReactMarkdown>{entry.content}</ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Chat messages for a day ───────────────────────────────────────────────────

function DayChatSection({ dateStr }) {
  const [messages, setMessages] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const load = useCallback(async () => {
    if (messages !== null) { setExpanded(v => !v); return }
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/journal/day/${dateStr}/messages`)
      if (!res.ok) throw new Error(res.statusText)
      const data = await res.json()
      setMessages(data.messages || [])
      setExpanded(true)
    } catch (e) {
      setMessages([])
    } finally {
      setLoading(false)
    }
  }, [dateStr, messages])

  const meta = ENTRY_TYPE_META.chat
  const msgCount = messages?.length ?? null

  return (
    <div className={`rounded-xl border ${meta.border} ${meta.bg} overflow-hidden`}>
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:brightness-110 transition-all select-none"
        onClick={load}
      >
        <span className="text-lg shrink-0">{meta.icon}</span>
        <div className="flex-1 min-w-0">
          <span className={`text-sm font-medium ${meta.color}`}>
            Conversation
          </span>
          {msgCount !== null && (
            <span className="text-xs text-slate-500 ml-2">· {msgCount} messages</span>
          )}
        </div>
        {loading
          ? <span className="text-xs text-slate-500">Loading...</span>
          : <span className={`text-slate-400 text-sm transition-transform ${expanded ? 'rotate-180' : ''}`}>▾</span>
        }
      </div>

      {expanded && messages && (
        <div className="px-4 pb-4 pt-1 border-t border-white/5 space-y-3 max-h-[600px] overflow-y-auto">
          {messages.length === 0 ? (
            <p className="text-sm text-slate-500 italic">No chat messages this day.</p>
          ) : messages.map((msg, i) => {
            const isUser = msg.role === 'user'
            const name = msg.metadata?.role_display || (isUser ? 'Jess' : 'Rowan')
            return (
              <div key={i} className={`flex gap-2 ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                  isUser
                    ? 'bg-emerald-700/50 text-emerald-100'
                    : 'bg-slate-700/60 text-slate-100'
                }`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs font-medium ${isUser ? 'text-emerald-300' : 'text-slate-400'}`}>
                      {name}
                    </span>
                    <span className="text-xs text-slate-500">{formatTime(msg.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap break-words leading-relaxed">{msg.content}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── User note composer ────────────────────────────────────────────────────────

function NoteComposer({ dateStr, onSaved }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const save = async () => {
    if (!text.trim()) return
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/journal/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, title: title || null, entry_date: dateStr }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || res.statusText)
      }
      setText('')
      setTitle('')
      setOpen(false)
      onSaved(dateStr)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full text-left px-4 py-2.5 rounded-xl border border-dashed border-amber-700/40 text-amber-400/70 hover:text-amber-300 hover:border-amber-600/60 text-sm transition-colors"
      >
        ✏️ Add a note for this day...
      </button>
    )
  }

  return (
    <div className="rounded-xl border border-amber-700/40 bg-amber-900/20 p-4 space-y-3">
      <input
        type="text"
        placeholder="Title (optional)"
        value={title}
        onChange={e => setTitle(e.target.value)}
        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
      />
      <textarea
        placeholder="Write your note..."
        value={text}
        onChange={e => setText(e.target.value)}
        rows={4}
        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 resize-none"
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex gap-2 justify-end">
        <button
          onClick={() => { setOpen(false); setText(''); setTitle(''); setError(null) }}
          className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200 rounded-lg transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={save}
          disabled={saving || !text.trim()}
          className="px-4 py-1.5 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded-lg disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving...' : 'Save Note'}
        </button>
      </div>
    </div>
  )
}

// ── Day section ───────────────────────────────────────────────────────────────

function DaySection({ day, onDelete, onNoteAdded, onEntryUpdated, entryFilter }) {
  const [collapsed, setCollapsed] = useState(false)
  const heading = formatDayHeading(day.date)
  const totalWords = day.entries.reduce((s, e) => s + (e.word_count || 0), 0)

  return (
    <div className="space-y-1">
      {/* Day header */}
      <button
        onClick={() => setCollapsed(v => !v)}
        className="w-full flex items-center gap-3 py-2 text-left group"
      >
        <div className="flex-1 h-px bg-slate-700/60" />
        <span className="shrink-0 text-sm font-semibold text-slate-300 group-hover:text-slate-100 transition-colors px-2">
          {heading}
        </span>
        <span className="text-xs text-slate-500">
          {day.entries.length} entr{day.entries.length === 1 ? 'y' : 'ies'} · {totalWords.toLocaleString()} words
        </span>
        <div className="flex-1 h-px bg-slate-700/60" />
        <span className={`text-slate-500 text-sm transition-transform ${collapsed ? '-rotate-90' : ''}`}>▾</span>
      </button>

      {!collapsed && (
        <div className="space-y-2 pl-0">
          {/* Rowan's entries */}
          {day.entries.map(entry => (
            <EntryCard
              key={entry.id}
              entry={entry}
              onDelete={onDelete}
              onUpdated={onEntryUpdated}
            />
          ))}
          {/* Conversation history (only when showing all) */}
          {entryFilter === 'all' && <DayChatSection dateStr={day.date} />}
          {/* User note composer (when all or user notes filter) */}
          {(entryFilter === 'all' || entryFilter === 'user_note') && (
            <NoteComposer dateStr={day.date} onSaved={onNoteAdded} />
          )}
        </div>
      )}
    </div>
  )
}

// ── Standalone note modal (for writing notes on any date) ────────────────────

function NewNoteModal({ onSaved, onClose }) {
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [dateStr, setDateStr] = useState(() => {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const save = async () => {
    if (!text.trim()) return
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/journal/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, title: title || null, entry_date: dateStr }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || res.statusText)
      }
      onSaved(dateStr)
    } catch (e) {
      setError(e.message)
      setSaving(false)
    }
  }

  // Close on backdrop click
  const onBackdrop = (e) => { if (e.target === e.currentTarget) onClose() }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onBackdrop}
    >
      <div className="w-full max-w-lg bg-slate-900 rounded-2xl border border-amber-700/40 shadow-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-amber-300">✏️ New Journal Entry</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200 text-xl leading-none">×</button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs text-slate-400 mb-1">Title (optional)</label>
            <input
              type="text"
              placeholder="e.g. Morning thoughts"
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Date</label>
            <input
              type="date"
              value={dateStr}
              onChange={e => setDateStr(e.target.value)}
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-slate-400 mb-1">Entry</label>
          <textarea
            placeholder="Write your thoughts..."
            value={text}
            onChange={e => setText(e.target.value)}
            rows={7}
            autoFocus
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 resize-none"
          />
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving || !text.trim()}
            className="px-5 py-2 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded-lg disabled:opacity-50 transition-colors font-medium"
          >
            {saving ? 'Saving...' : 'Save Entry'}
          </button>
        </div>
      </div>
    </div>
  )
}


// ── Main JournalTab ───────────────────────────────────────────────────────────

export default function JournalTab() {
  const [configured, setConfigured] = useState(null)
  const [months, setMonths] = useState([])
  const [currentMonth, setCurrentMonth] = useState(currentYearMonth())
  const [days, setDays] = useState([])
  const [loadingMonth, setLoadingMonth] = useState(false)
  const [error, setError] = useState(null)
  const [showNewNote, setShowNewNote] = useState(false)
  const [entryFilter, setEntryFilter] = useState('all')

  // Check status + load available months
  useEffect(() => {
    fetch(`${API_BASE}/journal/status`)
      .then(r => r.json())
      .then(d => {
        setConfigured(d.configured)
        if (d.configured) {
          return fetch(`${API_BASE}/journal/months`).then(r => r.json())
        }
      })
      .then(d => {
        if (d?.months) setMonths(d.months)
      })
      .catch(() => setConfigured(false))
  }, [])

  // Load entries for current month
  const loadMonth = useCallback(async (ym) => {
    setLoadingMonth(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/journal/month/${ym}`)
      if (!res.ok) throw new Error(res.statusText)
      const data = await res.json()
      setDays(data.days || [])
    } catch (e) {
      setError(e.message)
      setDays([])
    } finally {
      setLoadingMonth(false)
    }
  }, [])

  useEffect(() => {
    if (configured) loadMonth(currentMonth)
  }, [configured, currentMonth, loadMonth])

  const handleDelete = async (entryId) => {
    try {
      await fetch(`${API_BASE}/journal/entries/${entryId}`, { method: 'DELETE' })
      loadMonth(currentMonth)
    } catch (e) {
      console.error('Delete failed', e)
    }
  }

  const handleNoteAdded = (savedDate) => {
    // Navigate to the month the note was saved in, then reload
    if (savedDate) {
      const ym = savedDate.slice(0, 7)
      if (ym !== currentMonth) {
        setCurrentMonth(ym)
        // loadMonth will fire via useEffect when currentMonth changes
      } else {
        loadMonth(currentMonth)
      }
    } else {
      loadMonth(currentMonth)
    }
    setShowNewNote(false)
  }

  const canGoPrev = true
  const canGoNext = currentMonth < currentYearMonth()

  if (configured === null) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-slate-400">Loading journal...</span>
      </div>
    )
  }

  if (!configured) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center space-y-3">
        <p className="text-2xl">📖</p>
        <p className="text-slate-300 font-medium">Journal not available</p>
        <p className="text-slate-500 text-sm">
          Set <code className="text-slate-300">KNOWLEDGE_DATABASE_URL</code> in <code className="text-slate-300">.env</code> to enable the journal.
          It uses the same local PostgreSQL database as the Knowledge Bank.
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      {/* New note modal */}
      {showNewNote && (
        <NewNoteModal
          onSaved={handleNoteAdded}
          onClose={() => setShowNewNote(false)}
        />
      )}

      {/* Header + month nav */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-semibold text-slate-100">Journal</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Rowan's daily outputs, reflections, and your notes — all in one place.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setShowNewNote(true)}
            className="text-sm bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg transition-colors font-medium"
          >
            ✏️ New Entry
          </button>
          <button
            onClick={() => loadMonth(currentMonth)}
            className="text-sm text-emerald-400 hover:text-emerald-300 px-3 py-1.5 rounded-lg border border-emerald-500/30 hover:border-emerald-500/50 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Month navigator */}
      <div className="flex items-center justify-between bg-slate-800/60 rounded-xl px-4 py-3 border border-slate-700/50">
        <button
          onClick={() => setCurrentMonth(prevMonth(currentMonth))}
          disabled={!canGoPrev}
          className="text-slate-400 hover:text-slate-200 disabled:opacity-30 px-2 py-1 rounded transition-colors text-lg"
        >
          ◀
        </button>
        <div className="text-center">
          <p className="text-slate-100 font-semibold">{formatMonthLabel(currentMonth)}</p>
          {months.length > 0 && (
            <p className="text-xs text-slate-500 mt-0.5">
              {months.includes(currentMonth) ? `${days.length} day${days.length !== 1 ? 's' : ''} with entries` : 'No entries this month'}
            </p>
          )}
        </div>
        <button
          onClick={() => setCurrentMonth(nextMonth(currentMonth))}
          disabled={!canGoNext}
          className="text-slate-400 hover:text-slate-200 disabled:opacity-30 px-2 py-1 rounded transition-colors text-lg"
        >
          ▶
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2">
        {FILTER_OPTIONS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setEntryFilter(value)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              entryFilter === value
                ? 'bg-emerald-600 text-white'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1">
        {Object.entries(ENTRY_TYPE_META).map(([type, m]) => (
          <span key={type} className={`text-xs ${m.color} flex items-center gap-1`}>
            <span>{m.icon}</span> {m.label}
          </span>
        ))}
      </div>

      {/* Content */}
      {loadingMonth ? (
        <div className="flex items-center justify-center h-32">
          <span className="text-slate-400">Loading {formatMonthLabel(currentMonth)}...</span>
        </div>
      ) : error ? (
        <div className="text-center py-12 text-red-400 text-sm">{error}</div>
      ) : days.length === 0 ? (
        <div className="text-center py-16 space-y-4">
          <p className="text-3xl">📖</p>
          <p className="text-slate-400">No entries for {formatMonthLabel(currentMonth)}.</p>
          <p className="text-slate-500 text-sm">
            Entries appear here automatically when Rowan runs cron jobs or writes daily summaries.
          </p>
          <button
            onClick={() => setShowNewNote(true)}
            className="inline-flex items-center gap-2 text-sm bg-amber-600 hover:bg-amber-500 text-white px-4 py-2 rounded-lg transition-colors font-medium"
          >
            ✏️ Write your first entry for this month
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {days.map(day => {
            const filteredEntries = entryFilter === 'all'
              ? day.entries
              : day.entries.filter(e => entryMatchesFilter(e, entryFilter))
            const filteredDay = { ...day, entries: filteredEntries }
            if (filteredEntries.length === 0 && entryFilter !== 'all') return null
            return (
              <DaySection
                key={day.date}
                day={filteredDay}
                onDelete={handleDelete}
                onNoteAdded={handleNoteAdded}
                onEntryUpdated={() => loadMonth(currentMonth)}
                entryFilter={entryFilter}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

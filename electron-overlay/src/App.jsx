import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'

const API_BASE = 'http://localhost:8000'
const THREAD_ID = 'main'
// How long to wait for the agent to respond before giving up (ms).
// Kimi-K2.5 with tool calls can take 60-90s on complex queries.
const CHAT_TIMEOUT_MS = 3 * 60 * 1000 // 3 minutes
// Vision can also be slow (60s+ on Chutes/Kimi) — give it the same budget.
const VISION_TIMEOUT_MS = 3 * 60 * 1000 // 3 minutes

// Strip <actions>...</actions> tags the agent sometimes emits
const EMOJI_MAP = { heart: '❤️', smile: '😊', thumbsup: '👍', wave: '👋', star: '⭐' }
function cleanContent(text) {
  if (!text || typeof text !== 'string') return text
  return text
    .replace(/<actions>\s*<react\s+emoji="(\w+)"\s*\/>\s*<\/actions>/gi,
      (_, name) => (EMOJI_MAP[name?.toLowerCase()] ?? '') + ' ')
    .replace(/<actions>[\s\S]*?<\/actions>/gi, '')
    .trim()
}

// ── Icons (inline SVG, no icon library needed) ────────────────────────────────
const Icon = {
  Minimize: () => (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
      <rect x="1" y="5.5" width="10" height="1.5" rx="0.75"/>
    </svg>
  ),
  Close: () => (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
      <path d="M1.5 1.5L10.5 10.5M10.5 1.5L1.5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  ),
  Send: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13"/>
      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
  ),
  Camera: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
      <circle cx="12" cy="13" r="4"/>
    </svg>
  ),
  Eye: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  ),
  EyeOff: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
      <line x1="1" y1="1" x2="23" y2="23"/>
    </svg>
  ),
  Trash: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6"/>
      <path d="M19 6l-1 14H6L5 6"/>
      <path d="M10 11v6M14 11v6"/>
      <path d="M9 6V4h6v2"/>
    </svg>
  ),
  Mouse: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="2" width="14" height="20" rx="7"/>
      <line x1="12" y1="6" x2="12" y2="10"/>
    </svg>
  ),
}

// ── Screenshot preview thumbnail ──────────────────────────────────────────────
function ScreenshotPreview({ dataUrl, onRemove }) {
  return (
    <div className="relative inline-block mt-1 mb-1">
      <img
        src={dataUrl}
        alt="Screenshot preview"
        className="h-16 rounded border border-white/20 object-cover"
        style={{ maxWidth: '120px' }}
      />
      <button
        onClick={onRemove}
        className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-red-500 text-white flex items-center justify-center hover:bg-red-400 transition-colors no-drag"
        title="Remove screenshot"
      >
        <svg width="8" height="8" viewBox="0 0 12 12" fill="currentColor">
          <path d="M1.5 1.5L10.5 10.5M10.5 1.5L1.5 10.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
        </svg>
      </button>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null) // e.g. "Analyzing screenshot..." or "Waiting for Rowan..."

  // Overlay controls
  const [opacity, setOpacity] = useState(0.92)
  const [clickThrough, setClickThrough] = useState(false)
  const [showControls, setShowControls] = useState(false)

  // Screenshot
  const [pendingScreenshot, setPendingScreenshot] = useState(null) // base64 dataURL
  const [screenshotLoading, setScreenshotLoading] = useState(false)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const loadingRef = useRef(false)

  const isElectron = typeof window !== 'undefined' && !!window.electronAPI

  // ── Scroll to bottom ────────────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // ── Opacity sync to Electron ────────────────────────────────────────────────
  useEffect(() => {
    if (isElectron) window.electronAPI.setOpacity(opacity)
  }, [opacity, isElectron])

  // ── Click-through sync ──────────────────────────────────────────────────────
  useEffect(() => {
    if (isElectron) window.electronAPI.setClickThrough(clickThrough)
  }, [clickThrough, isElectron])

  // ── Listen for hotkey-triggered screenshot ──────────────────────────────────
  useEffect(() => {
    if (!isElectron) return
    const cleanup = window.electronAPI.onTriggerScreenshot(() => {
      handleScreenshot()
    })
    return cleanup
  }, [isElectron])

  // ── Load conversation history ────────────────────────────────────────────────
  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/messages?thread_id=${THREAD_ID}&limit=100`)
      if (!res.ok) return
      const data = await res.json()
      setMessages(data.messages || [])
    } catch {
      // silently ignore — agent may not be running yet
    } finally {
      setHistoryLoaded(true)
    }
  }, [])

  useEffect(() => {
    loadHistory()
    const interval = setInterval(() => {
      if (!loadingRef.current) loadHistory()
    }, 10000)
    return () => clearInterval(interval)
  }, [loadHistory])

  // ── Screenshot capture ───────────────────────────────────────────────────────
  const handleScreenshot = useCallback(async () => {
    if (!isElectron || screenshotLoading) return
    setScreenshotLoading(true)
    try {
      const dataUrl = await window.electronAPI.captureScreenshot()
      if (dataUrl) {
        setPendingScreenshot(dataUrl)
        inputRef.current?.focus()
      }
    } catch (err) {
      console.error('Screenshot failed:', err)
    } finally {
      setScreenshotLoading(false)
    }
  }, [isElectron, screenshotLoading])

  // ── Fetch with timeout helper ─────────────────────────────────────────────
  const fetchWithTimeout = useCallback((url, options, timeoutMs = CHAT_TIMEOUT_MS) => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    return fetch(url, { ...options, signal: controller.signal })
      .finally(() => clearTimeout(timer))
  }, [])

  // ── Send message ─────────────────────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if ((!text && !pendingScreenshot) || loading) return

    const hasScreenshot = !!pendingScreenshot
    const screenshotData = pendingScreenshot
    const userPrompt = text || 'I sent you a screenshot of my screen. What do you see?'

    setInput('')
    setPendingScreenshot(null)
    setError(null)
    setStatus(null)
    loadingRef.current = true
    setLoading(true)

    // Optimistic user message shown immediately
    setMessages((prev) => [
      ...prev,
      {
        role: 'user',
        content: userPrompt + (hasScreenshot ? ' [screenshot]' : ''),
        metadata: { role_display: 'User' },
        _optimistic: true,
      },
    ])

    try {
      let finalMessage = userPrompt

      if (hasScreenshot) {
        // Step 1: Send image to the vision endpoint.
        // Vision on Chutes/Kimi can take 60s+ — use the full 3-minute budget.
        setStatus('Analyzing screenshot...')
        const visionRes = await fetchWithTimeout(
          `${API_BASE}/analyze-screenshot`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_data_url: screenshotData, prompt: userPrompt }),
          },
          VISION_TIMEOUT_MS,
        )

        if (!visionRes.ok) {
          const err = await visionRes.json().catch(() => ({ detail: visionRes.statusText }))
          throw new Error(`Vision analysis failed: ${err.detail || visionRes.statusText}`)
        }

        const visionData = await visionRes.json()
        // Step 2: Combine the user's question with the vision description as context
        finalMessage = `${userPrompt}\n\n[Screenshot analysis]:\n${visionData.description}`
      }

      // Step 3: Send the text-only message to the agent
      setStatus('Waiting for Rowan...')
      const res = await fetchWithTimeout(
        `${API_BASE}/chat`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: finalMessage,
            thread_id: THREAD_ID,
            channel_type: 'overlay',
          }),
        },
        CHAT_TIMEOUT_MS,
      )

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      // Reload history to get the real persisted messages (replaces the optimistic one)
      await loadHistory()
    } catch (err) {
      // AbortError means we hit the timeout — the agent may still be running.
      // Poll for the response rather than showing a hard error.
      if (err.name === 'AbortError') {
        setStatus(null)
        setError('Taking longer than expected — polling for response...')
        let attempts = 0
        const maxAttempts = 60
        const poll = setInterval(async () => {
          attempts++
          try {
            const res = await fetch(`${API_BASE}/messages?thread_id=${THREAD_ID}&limit=5`)
            if (res.ok) {
              const data = await res.json()
              const msgs = (data.messages || []).filter((m) => m.role !== 'tool')
              const lastMsg = msgs[msgs.length - 1]
              if (lastMsg?.role === 'assistant') {
                clearInterval(poll)
                setError(null)
                await loadHistory()
                loadingRef.current = false
                setLoading(false)
                return
              }
            }
          } catch { /* keep polling */ }
          if (attempts >= maxAttempts) {
            clearInterval(poll)
            setError('No response after 5 minutes. The agent may still be processing.')
            loadingRef.current = false
            setLoading(false)
          }
        }, 5000)
        return
      }

      setStatus(null)
      setError(err.message || 'Failed to send message')
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: null, metadata: {}, error: err.message || 'Something went wrong.' },
      ])
    } finally {
      setStatus(null)
      loadingRef.current = false
      setLoading(false)
    }
  }, [input, pendingScreenshot, loading, loadHistory, fetchWithTimeout])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const clearHistory = () => {
    setMessages([])
    setHistoryLoaded(false)
    setTimeout(loadHistory, 100)
  }

  const visibleMessages = messages.filter((m) => m.role !== 'tool')

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div
      className="flex flex-col h-full rounded-xl overflow-hidden"
      style={{
        background: `rgba(15, 20, 30, ${Math.min(opacity, 0.97)})`,
        border: '1px solid rgba(255,255,255,0.08)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
      }}
    >
      {/* ── Title Bar (drag handle) ─────────────────────────────────────────── */}
      <div
        className="drag-region flex items-center justify-between px-3 py-2 flex-shrink-0"
        style={{ background: 'rgba(255,255,255,0.04)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}
      >
        {/* Left: name + status dot */}
        <div className="flex items-center gap-2 no-drag">
          <div className="w-2 h-2 rounded-full bg-emerald-400" title="Agent online" />
          <span className="text-xs font-semibold text-slate-200 tracking-wide">ROWAN</span>
          <span className="text-xs text-slate-500">overlay</span>
        </div>

        {/* Right: controls toggle + window buttons */}
        <div className="flex items-center gap-1 no-drag">
          {/* Settings toggle */}
          <button
            onClick={() => setShowControls((v) => !v)}
            className={`px-2 py-1 rounded text-xs transition-colors ${
              showControls ? 'bg-white/10 text-slate-200' : 'text-slate-500 hover:text-slate-300 hover:bg-white/5'
            }`}
            title="Toggle controls"
          >
            ⚙
          </button>

          {/* Minimize */}
          {isElectron && (
            <button
              onClick={() => window.electronAPI.minimize()}
              className="w-6 h-6 rounded flex items-center justify-center text-slate-500 hover:text-slate-300 hover:bg-white/10 transition-colors"
              title="Minimize"
            >
              <Icon.Minimize />
            </button>
          )}

          {/* Hide (Ctrl+Shift+R to bring back) */}
          {isElectron && (
            <button
              onClick={() => window.electronAPI.hide()}
              className="w-6 h-6 rounded flex items-center justify-center text-slate-500 hover:text-red-400 hover:bg-white/10 transition-colors"
              title="Hide overlay (Ctrl+Shift+R to show again)"
            >
              <Icon.Close />
            </button>
          )}
        </div>
      </div>

      {/* ── Controls Panel ──────────────────────────────────────────────────── */}
      {showControls && (
        <div
          className="px-3 py-2.5 flex-shrink-0 space-y-2.5 no-drag"
          style={{ background: 'rgba(0,0,0,0.25)', borderBottom: '1px solid rgba(255,255,255,0.05)' }}
        >
          {/* Opacity slider */}
          <div className="flex items-center gap-2">
            <Icon.Eye />
            <span className="text-xs text-slate-400 w-14 flex-shrink-0">Opacity</span>
            <input
              type="range"
              min="0.2"
              max="1.0"
              step="0.05"
              value={opacity}
              onChange={(e) => setOpacity(parseFloat(e.target.value))}
              className="flex-1 h-1.5 accent-emerald-400 cursor-pointer"
              title={`Opacity: ${Math.round(opacity * 100)}%`}
            />
            <span className="text-xs text-slate-400 w-8 text-right">{Math.round(opacity * 100)}%</span>
          </div>

          {/* Click-through toggle */}
          {isElectron && (
            <div className="flex items-center gap-2">
              <Icon.Mouse />
              <span className="text-xs text-slate-400 flex-1">Click-through</span>
              <button
                onClick={() => setClickThrough((v) => !v)}
                className={`relative w-9 h-5 rounded-full transition-colors ${
                  clickThrough ? 'bg-amber-500' : 'bg-slate-600'
                }`}
                title={clickThrough ? 'Click-through ON (clicks go to WoW)' : 'Click-through OFF (overlay is interactive)'}
              >
                <span
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                    clickThrough ? 'translate-x-4' : 'translate-x-0.5'
                  }`}
                />
              </button>
              {clickThrough && (
                <span className="text-xs text-amber-400">WoW mode</span>
              )}
            </div>
          )}

          {/* Clear chat */}
          <div className="flex items-center gap-2">
            <Icon.Trash />
            <span className="text-xs text-slate-400 flex-1">Clear display</span>
            <button
              onClick={clearHistory}
              className="text-xs text-slate-500 hover:text-red-400 px-2 py-0.5 rounded border border-slate-700 hover:border-red-500/50 transition-colors"
            >
              Clear
            </button>
          </div>

          {/* Hotkeys reminder */}
          <div className="text-xs text-slate-600 space-y-0.5 pt-0.5 border-t border-white/5">
            <div><kbd className="text-slate-500">Ctrl+Shift+R</kbd> — show/hide overlay</div>
            <div><kbd className="text-slate-500">Ctrl+Shift+S</kbd> — screenshot + open</div>
          </div>
        </div>
      )}

      {/* ── Messages ────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2 no-drag">
        {!historyLoaded ? (
          <div className="flex items-center justify-center h-full">
            <span className="text-xs text-slate-500">Connecting to Agent...</span>
          </div>
        ) : visibleMessages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <p className="text-xs text-slate-500">No messages yet.</p>
              <p className="text-xs text-slate-600 mt-1">Type below or press Ctrl+Shift+S to send a screenshot.</p>
            </div>
          </div>
        ) : null}

        {visibleMessages.map((msg, i) => {
          const isCron = msg.metadata?.role_display === 'cron'

          if (isCron) {
            return (
              <div key={i} className="flex justify-start">
                <div className="max-w-[90%]">
                  <p className="text-xs text-indigo-400 mb-0.5">⏰ Cron</p>
                  <div
                    className="rounded-xl px-3 py-2 text-xs"
                    style={{ background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.25)', color: '#c7d2fe' }}
                  >
                    <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                  </div>
                </div>
              </div>
            )
          }

          const isUser = msg.role === 'user'
          return (
            <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
              <div
                className="max-w-[90%] rounded-xl px-3 py-2 text-xs"
                style={
                  isUser
                    ? { background: 'rgba(16,185,129,0.25)', border: '1px solid rgba(16,185,129,0.3)', color: '#d1fae5' }
                    : msg.error
                      ? { background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', color: '#fca5a5' }
                      : { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)', color: '#e2e8f0' }
                }
              >
                {isUser ? (
                  <p className="whitespace-pre-wrap break-words">{msg.content ?? msg.error}</p>
                ) : (
                  <div className="prose-overlay">
                    <ReactMarkdown
                      components={{
                        p: ({ children }) => <p className="whitespace-pre-wrap break-words">{children}</p>,
                      }}
                    >
                      {cleanContent(msg.content) ?? msg.error ?? ''}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {/* Loading indicator with status label */}
        {loading && (
          <div className="flex justify-start">
            <div
              className="rounded-xl px-3 py-2 flex items-center gap-2"
              style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }}
            >
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '-0.3s' }} />
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '-0.15s' }} />
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" />
              </span>
              {status && (
                <span className="text-xs text-slate-500 italic">{status}</span>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Input Area ──────────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 px-2 pb-2 pt-1.5 no-drag"
        style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
      >
        {/* Screenshot preview */}
        {pendingScreenshot && (
          <div className="px-1 mb-1">
            <ScreenshotPreview
              dataUrl={pendingScreenshot}
              onRemove={() => setPendingScreenshot(null)}
            />
          </div>
        )}

        {/* Error */}
        {error && (
          <p className="text-xs text-red-400 px-1 mb-1">{error}</p>
        )}

        <div className="flex gap-1.5 items-end">
          {/* Screenshot button */}
          {isElectron && (
            <button
              onClick={handleScreenshot}
              disabled={loading || screenshotLoading}
              className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${
                pendingScreenshot
                  ? 'bg-emerald-600/40 text-emerald-300 border border-emerald-500/40'
                  : 'text-slate-500 hover:text-slate-300 border border-transparent hover:border-white/10 hover:bg-white/5'
              } disabled:opacity-40 disabled:cursor-not-allowed`}
              title="Capture screenshot (Ctrl+Shift+S)"
            >
              {screenshotLoading ? (
                <span className="w-3 h-3 border border-slate-400 border-t-transparent rounded-full animate-spin" />
              ) : (
                <Icon.Camera />
              )}
            </button>
          )}

          {/* Text input */}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={clickThrough ? 'Click-through ON — toggle off to type' : 'Message Agent... (Enter to send)'}
            disabled={loading || clickThrough}
            rows={1}
            className="flex-1 rounded-lg px-3 py-2 text-xs resize-none focus:outline-none disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: '#e2e8f0',
              minHeight: '32px',
              maxHeight: '80px',
            }}
            onInput={(e) => {
              // Auto-resize textarea
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 80) + 'px'
            }}
          />

          {/* Send button */}
          <button
            onClick={sendMessage}
            disabled={loading || (!input.trim() && !pendingScreenshot) || clickThrough}
            className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title="Send (Enter)"
          >
            <Icon.Send />
          </button>
        </div>
      </div>
    </div>
  )
}

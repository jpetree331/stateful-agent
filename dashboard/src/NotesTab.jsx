/**
 * Notes tab — Milanote-style corkboard with sticky notes and checklists.
 * Right sidebar: drag to add notes/checklists, or font styling when a note is selected.
 * Test mode: npm run dev:test or ?test=1 — uses localStorage instead of PostgreSQL.
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core'
import ReactMarkdown from 'react-markdown'
import * as notesApi from './notesApi'

function stripHtml(html) {
  if (!html) return ''
  const div = document.createElement('div')
  div.innerHTML = html
  return div.textContent || div.innerText || ''
}

function markdownToHtml(md) {
  if (!md) return ''
  return md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/_(.+?)_/g, '<em>$1</em>')
    .replace(/\n/g, '<br>')
}

// Sticky note color palette (white first, then presets)
const BG_COLORS = [
  '#ffffff', '#fef08a', '#fecaca', '#bbf7d0', '#bfdbfe', '#e9d5ff',
  '#fed7aa', '#a5f3fc', '#fde68a', '#d9f99d', '#fbcfe8',
]
const HEADER_COLORS = [
  '#eab308', '#ef4444', '#22c55e', '#3b82f6', '#a855f7',
  '#f97316', '#06b6d4', '#ca8a04', '#84cc16', '#ec4899',
]

// Copy icon (two stacked papers)
function CopyIcon({ className = 'w-4 h-4' }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

// ==================== STYLING TOOLBAR ====================

function StylingToolbar({ editorRef, selectedColor = '#000000', onCopyNote, copyFeedback, useMarkdown }) {
  const fonts = ['Inter', 'Georgia', 'Monaco', 'Comic Sans MS', 'Courier New']

  const exec = (cmd, value) => {
    const el = editorRef?.current?.current ?? editorRef?.current
    el?.focus()
    document.execCommand(cmd, false, value ?? null)
  }

  return (
    <div className="space-y-4">
      {onCopyNote && (
        <div className="mb-3">
          <button
            type="button"
            onClick={onCopyNote}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 transition-colors"
            title="Copy note text"
          >
            <CopyIcon />
            <span className="text-sm">{copyFeedback ? 'Copied!' : 'Copy note'}</span>
          </button>
        </div>
      )}
      {useMarkdown ? (
        <p className="text-xs text-slate-500">Use **bold**, *italic*, # headers, - lists in your text.</p>
      ) : (
        <>
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Format</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onMouseDown={(e) => { e.preventDefault(); exec('bold') }}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200"
          title="Bold"
        >
          <strong>B</strong>
        </button>
        <button
          type="button"
          onMouseDown={(e) => { e.preventDefault(); exec('italic') }}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 italic"
          title="Italic"
        >
          I
        </button>
        <button
          type="button"
          onMouseDown={(e) => { e.preventDefault(); exec('underline') }}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 underline"
          title="Underline"
        >
          U
        </button>
        <button
          type="button"
          onMouseDown={(e) => { e.preventDefault(); exec('strikeThrough') }}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 line-through"
          title="Strikethrough"
        >
          S
        </button>
      </div>
      <div>
        <p className="text-xs text-slate-500 mb-1">Font</p>
        <select
          onChange={(e) => exec('fontName', e.target.value)}
          className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-200"
        >
          {fonts.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </div>
      <div>
        <p className="text-xs text-slate-500 mb-1">Text color</p>
        <input
          type="color"
          value={selectedColor}
          onChange={(e) => {
            const el = editorRef?.current?.current ?? editorRef?.current
            el?.focus()
            document.execCommand('foreColor', false, e.target.value)
          }}
          className="w-full h-8 rounded cursor-pointer bg-slate-800 border border-slate-700"
        />
      </div>
        </>
      )}
    </div>
  )
}

// ==================== DRAG OVERLAY PREVIEW ====================

function NoteDragPreview({ item }) {
  const isNote = item?.item_type === 'note'
  const w = item?.size?.width ?? (isNote ? 200 : 220)
  const h = item?.size?.height ?? (isNote ? 180 : 200)
  const title = item?.content?.title?.trim()
  const showTitle = item?.content?.show_title === true
  const showHeader = item?.content?.show_header === true
  return (
    <div
      className="rounded-lg shadow-xl cursor-grabbing overflow-hidden flex flex-col"
      style={{
        width: w,
        height: h,
        backgroundColor: item?.background_color ?? '#fef08a',
        ...(showHeader && { borderTop: `4px solid ${item?.header_color ?? '#eab308'}` }),
      }}
    >
      {showTitle && title && (
        <div
          className="px-3 py-2.5 flex-shrink-0 text-[15px] font-medium text-slate-800 truncate tracking-tight"
          style={{
            backgroundColor: showHeader ? `${item?.header_color ?? '#eab308'}12` : 'rgba(0,0,0,0.04)',
            borderBottom: '1px solid rgba(0,0,0,0.06)',
            textAlign: item?.content?.title_align || 'left',
          }}
        >
          {title}
        </div>
      )}
      {isNote ? (
        <div
          className="flex-1 p-3 text-sm text-slate-700 overflow-hidden"
          dangerouslySetInnerHTML={{ __html: item?.content?.html || '' }}
        />
      ) : (
        <div className="flex-1 p-3 text-sm text-slate-800 overflow-hidden">
          {(item?.content?.items ?? []).slice(0, 3).map((it, i) => (
            <div key={i} className="flex items-center gap-2 mb-1">
              <span className={it.checked ? 'line-through text-slate-500' : ''}>{it.text || '…'}</span>
            </div>
          ))}
          {(item?.content?.items?.length ?? 0) > 3 && (
            <span className="text-slate-500 text-xs">+{(item.content.items.length - 3)} more</span>
          )}
        </div>
      )}
    </div>
  )
}

// ==================== ADD ITEMS (DRAGGABLE FROM SIDEBAR) ====================

function AddNoteDraggable({ type, bgColor, headerColor, onAdd, children }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `add-${type}`,
    data: { type: `add-${type}`, itemType: type, bgColor, headerColor },
  })
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      onClick={() => onAdd(type, bgColor, headerColor)}
      className={`flex items-center gap-3 p-3 rounded-xl border border-slate-700 transition-colors text-left cursor-grab active:cursor-grabbing ${
        isDragging ? 'opacity-50' : 'bg-slate-800 hover:bg-slate-700'
      }`}
    >
      {children}
    </div>
  )
}

function AddNotePalette({ onAdd }) {
  const [customBg, setCustomBg] = useState('#ffffff')
  return (
    <div className="space-y-3">
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Add to board</p>
      <p className="text-xs text-slate-500">Drag onto board or click to add</p>
      <div className="flex flex-col gap-2">
        <AddNoteDraggable
          type="note"
          bgColor="#fef08a"
          headerColor="#eab308"
          onAdd={onAdd}
        >
          <div className="w-10 h-10 rounded-lg bg-[#fef08a]" />
          <span className="text-sm font-medium text-slate-200">Note</span>
        </AddNoteDraggable>
        <AddNoteDraggable
          type="checklist"
          bgColor="#bbf7d0"
          headerColor="#22c55e"
          onAdd={onAdd}
        >
          <div className="w-10 h-10 rounded-lg bg-[#bbf7d0] flex items-center justify-center text-slate-600">
            ☑
          </div>
          <span className="text-sm font-medium text-slate-200">Checklist</span>
        </AddNoteDraggable>
      </div>
      <div className="pt-2 border-t border-slate-700">
        <p className="text-xs text-slate-500 mb-2">Background color</p>
        <div className="flex flex-wrap gap-1">
          {BG_COLORS.map((c, i) => (
            <button
              key={c}
              type="button"
              onClick={() => onAdd('note', c, HEADER_COLORS[i])}
              className="w-6 h-6 rounded border border-slate-600 hover:scale-110 transition-transform"
              style={{ backgroundColor: c }}
              title={c}
            />
          ))}
        </div>
        <div className="mt-2">
          <p className="text-xs text-slate-500 mb-1">Custom</p>
          <div className="flex gap-2 items-center">
            <input
              type="color"
              value={customBg}
              onChange={(e) => setCustomBg(e.target.value)}
              className="h-8 w-14 rounded cursor-pointer bg-slate-800 border border-slate-700"
            />
            <button
              type="button"
              onClick={() => onAdd('note', customBg, HEADER_COLORS[0])}
              className="text-xs text-slate-400 hover:text-emerald-400"
            >
              Add note with this color
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Word count for convert-to-doc prompt (Milanote-style)
const DOC_WORD_THRESHOLD = 800
const DOC_ICON_SIZE = 72

function countWords(html) {
  if (!html) return 0
  const div = document.createElement('div')
  div.innerHTML = html
  const text = (div.textContent || div.innerText || '').trim()
  return text ? text.split(/\s+/).filter(Boolean).length : 0
}

// ==================== STICKY NOTE ====================

function StickyNote({
  item,
  isSelected,
  onSelect,
  onUpdate,
  onDelete,
  onContentChange,
  onConvertToDoc,
  registerEditorRef,
  onResizePreview,
}) {
  const editorRef = useRef(null)
  const convertShownRef = useRef(false)
  const [showConvertModal, setShowConvertModal] = useState(false)
  const [isEditingMarkdown, setIsEditingMarkdown] = useState(false)
  const [localMarkdown, setLocalMarkdown] = useState(item.content?.markdown ?? '')
  const showTitle = item.content?.show_title === true
  const showHeader = item.content?.show_header === true
  const useMarkdown = item.content?.use_markdown === true
  const debouncedSaveMarkdown = useDebounce((md) => onContentChange({ markdown: md }), 400)

  useEffect(() => {
    setLocalMarkdown(item.content?.markdown ?? '')
  }, [item.id])
  const handleResize = (update) => {
    if (onResizePreview) onResizePreview(item.id, update)
    else onUpdate(item.id, update)
  }
  const handleResizeEnd = (update) => onUpdate(item.id, update)

  useEffect(() => {
    if (isSelected && (!useMarkdown || isEditingMarkdown)) registerEditorRef?.(editorRef)
    else registerEditorRef?.(null)
  }, [isSelected, useMarkdown, isEditingMarkdown, registerEditorRef])

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `note-${item.id}`,
    data: { type: 'item', item },
  })

  const handleBlur = () => {
    if (!editorRef.current) return
    const html = editorRef.current.innerHTML
    if (item.content?.html !== html) {
      onContentChange({ html })
    }
  }

  const handleInput = () => {
    if (!onConvertToDoc) return
    const content = useMarkdown ? (item.content?.markdown ?? '') : (editorRef.current?.innerHTML ?? '')
    const words = countWords(content)
    if (words >= DOC_WORD_THRESHOLD && !convertShownRef.current) {
      convertShownRef.current = true
      setShowConvertModal(true)
    }
  }

  useEffect(() => {
    if (useMarkdown && onConvertToDoc && countWords(item.content?.markdown ?? '') >= DOC_WORD_THRESHOLD && !convertShownRef.current) {
      convertShownRef.current = true
      setShowConvertModal(true)
    }
  }, [item.content?.markdown, useMarkdown, onConvertToDoc])


  const handleConvertConfirm = () => {
    setShowConvertModal(false)
    if (!useMarkdown && editorRef.current) {
      const html = editorRef.current.innerHTML
      if (item.content?.html !== html) onContentChange({ html })
    }
    onConvertToDoc?.(item)
  }

  useEffect(() => {
    if (!editorRef.current) return
    if (document.activeElement && editorRef.current.contains(document.activeElement)) return
    const html = item.content?.html ?? ''
    if (editorRef.current.innerHTML !== html) {
      editorRef.current.innerHTML = html
    }
  }, [item.id, item.content?.html])

  // Filter drag listeners so resize handle doesn't trigger drag
  const dragListeners = useMemo(() => {
    const skip = (e) => e.target?.closest('[data-resize-handle]')
    return Object.fromEntries(
      Object.entries(listeners).map(([k, v]) => [
        k,
        typeof v === 'function' ? (e) => { if (!skip(e)) v(e) } : v,
      ])
    )
  }, [listeners])

  return (
    <div
      ref={setNodeRef}
      {...attributes}
      className={`absolute rounded-lg shadow-lg overflow-hidden transition-shadow flex flex-col ${
        isSelected ? 'ring-2 ring-emerald-500 ring-offset-2 ring-offset-slate-900' : ''
      } ${isDragging ? 'opacity-0 pointer-events-none' : ''}`}
      style={{
        left: item.position?.x ?? 0,
        top: item.position?.y ?? 0,
        width: item.size?.width ?? 200,
        height: item.size?.height ?? 180,
        backgroundColor: item.background_color,
        ...(showHeader && { borderTop: `4px solid ${item.header_color}` }),
      }}
      onClick={(e) => {
        e.stopPropagation()
        onSelect(item, e)
      }}
    >
      {/* Drag handle: top bar only — delete button top-right, invisible until hover */}
      <div
        {...dragListeners}
        className="group flex justify-end gap-1 p-1 h-7 flex-shrink-0 cursor-grab active:cursor-grabbing hover:bg-black/5 rounded-t-lg transition-colors"
        data-drag-handle
      >
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(item.id) }}
          className="p-1 rounded bg-red-500/80 text-white text-xs hover:bg-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
          title="Delete (user only)"
        >
          ×
        </button>
      </div>
      {/* Milanote-style title header */}
      {showTitle && (
        <div
          className="flex-shrink-0 px-3 py-2.5"
          style={{
            backgroundColor: showHeader ? `${item.header_color}12` : 'rgba(0,0,0,0.04)',
            borderBottom: '1px solid rgba(0,0,0,0.06)',
            textAlign: item.content?.title_align || 'left',
          }}
        >
          <input
            type="text"
            value={item.content?.title ?? ''}
            onChange={(e) => onContentChange({ title: e.target.value })}
            onClick={(e) => { e.stopPropagation(); onSelect(item, e) }}
            placeholder="Add a title..."
            className="w-full bg-transparent border-none outline-none text-[15px] font-medium text-slate-800 placeholder:text-slate-400/80 focus:ring-0 p-0 tracking-tight cursor-text"
            style={{ textAlign: item.content?.title_align || 'left' }}
          />
        </div>
      )}
      {useMarkdown ? (
        isEditingMarkdown ? (
          <textarea
            ref={editorRef}
            value={localMarkdown}
            onChange={(e) => {
              const v = e.target.value
              setLocalMarkdown(v)
              debouncedSaveMarkdown(v)
            }}
            onBlur={() => {
              onContentChange({ markdown: localMarkdown })
              setIsEditingMarkdown(false)
            }}
            onClick={(e) => { e.stopPropagation(); onSelect(item, e) }}
            className="w-full flex-1 p-3 text-sm text-slate-700 overflow-auto outline-none resize-none bg-transparent border-none font-inherit"
            style={{ minHeight: 0 }}
            placeholder="Write something... (Markdown supported)"
          />
        ) : (
          <div
            onClick={(e) => { e.stopPropagation(); onSelect(item, e); setLocalMarkdown(item.content?.markdown ?? ''); setIsEditingMarkdown(true) }}
            className="w-full flex-1 p-3 text-sm text-slate-700 overflow-auto outline-none cursor-text prose prose-sm prose-slate max-w-none"
            style={{ minHeight: 0 }}
          >
            {(item.content?.markdown ?? '').trim() ? (
              <ReactMarkdown>{item.content.markdown}</ReactMarkdown>
            ) : (
              <span className="text-slate-400">Click to write... (Markdown supported)</span>
            )}
          </div>
        )
      ) : (
        <div
          ref={editorRef}
          contentEditable
          suppressContentEditableWarning
          onBlur={handleBlur}
          onInput={handleInput}
          onClick={(e) => { e.stopPropagation(); onSelect(item, e) }}
          className="w-full flex-1 p-3 text-sm text-slate-700 overflow-auto outline-none resize-none"
          style={{ minHeight: 0 }}
          data-placeholder="Write something..."
        />
      )}
      {showConvertModal && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/50 rounded-lg p-4">
          <div className="bg-slate-800 rounded-xl p-5 shadow-xl max-w-sm border border-slate-600">
            <p className="text-slate-200 text-sm mb-4">
              This note is getting long. Convert to a doc for easier writing? It will expand to fill the board. When you&apos;re done, click outside to save and shrink to an icon.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setShowConvertModal(false)}
                className="px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700"
              >
                Keep as note
              </button>
              <button
                type="button"
                onClick={handleConvertConfirm}
                className="px-3 py-1.5 rounded-lg text-sm bg-emerald-600 text-white hover:bg-emerald-500"
              >
                Convert to doc
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Resize handles — all four corners */}
      {(['se', 'sw', 'nw']).map((corner) => {
        const pos = { se: 'bottom-0 right-0', sw: 'bottom-0 left-0', ne: 'top-0 right-0', nw: 'top-0 left-0' }[corner]
        const cursor = { se: 'cursor-se-resize', sw: 'cursor-sw-resize', ne: 'cursor-ne-resize', nw: 'cursor-nw-resize' }[corner]
        const rounded = { se: 'rounded-tl', sw: 'rounded-tr', ne: 'rounded-bl', nw: 'rounded-br' }[corner]
        const flex = { se: 'items-end justify-end', sw: 'items-end justify-start', ne: 'items-start justify-end', nw: 'items-start justify-start' }[corner]
        return (
          <div
            key={corner}
            data-resize-handle
            onMouseDown={getResizeHandler(item, handleResize, handleResizeEnd, corner)}
            className={`absolute w-5 h-5 ${pos} ${cursor} hover:bg-black/10 ${rounded} flex ${flex} p-0.5`}
            title="Resize"
          >
            <span className="text-slate-500/60 text-[10px] font-mono">⋰</span>
          </div>
        )
      })}
    </div>
  )
}

// ==================== DOC (MILANOTE-STYLE LONG-FORM) ====================

function DocExpandedOverlay({ item, onCollapse, onContentChange }) {
  const editorRef = useRef(null)

  const getContentPatch = () => {
    if (!editorRef.current) return null
    const html = editorRef.current.innerHTML
    if (item.content?.html !== html) return { html }
    return null
  }

  const handleBackdropClick = () => {
    const patch = getContentPatch()
    onCollapse?.(patch ?? {})
  }

  const handleBlur = () => {
    const patch = getContentPatch()
    if (patch) onContentChange(patch)
  }

  useEffect(() => {
    if (!editorRef.current) return
    const html = item.content?.html ?? ''
    if (editorRef.current.innerHTML !== html) {
      editorRef.current.innerHTML = html
    }
    editorRef.current.focus()
  }, [item.id, item.content?.html])

  return (
    <>
      <div
        onClick={handleBackdropClick}
        className="absolute inset-0 z-40 bg-black/40"
        aria-hidden
      />
      <div
        onClick={(e) => e.stopPropagation()}
        className="absolute inset-[1in] z-50 flex flex-col rounded-xl shadow-2xl overflow-hidden bg-white border border-slate-200"
        style={{
          borderTop: `4px solid ${item.header_color ?? '#eab308'}`,
        }}
      >
      <div
        className="flex-shrink-0 px-4 py-3 flex items-center justify-between"
        style={{ backgroundColor: `${item.header_color ?? '#eab308'}18` }}
        onClick={(e) => e.stopPropagation()}
      >
        <input
          type="text"
          value={item.content?.title ?? ''}
          onChange={(e) => onContentChange({ title: e.target.value })}
          placeholder="Name your doc..."
          className="flex-1 bg-transparent border-none outline-none text-lg font-medium text-slate-800 placeholder:text-slate-400"
        />
        <button
          type="button"
          onClick={() => {
            const patch = getContentPatch()
            onCollapse?.(patch ?? {})
          }}
          className="ml-2 px-3 py-1 rounded-lg text-sm text-slate-600 hover:bg-slate-200"
        >
          Done
        </button>
      </div>
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        onBlur={handleBlur}
        onClick={(e) => e.stopPropagation()}
        className="flex-1 p-6 text-slate-700 overflow-auto outline-none min-h-0 prose prose-slate max-w-none"
        style={{ backgroundColor: item.background_color ?? '#ffffff' }}
      />
      </div>
    </>
  )
}

function DocNote({
  item,
  isExpanded,
  isSelected,
  onExpand,
  onCollapse,
  onSelect,
  onUpdate,
  onDelete,
  onContentChange,
}) {
  const title = (item.content?.title ?? '').trim() || 'Untitled doc'
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `note-${item.id}`,
    data: { type: 'item', item },
  })

  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      onClick={(e) => { e.stopPropagation(); onSelect?.(item, e) }}
      onDoubleClick={(e) => { e.stopPropagation(); onExpand?.() }}
      className={`absolute rounded-lg shadow-lg overflow-hidden cursor-pointer transition-shadow flex flex-col items-center justify-center flex-shrink-0 ${
        isSelected ? 'ring-2 ring-emerald-500 ring-offset-2 ring-offset-slate-900' : ''
      } ${isDragging ? 'opacity-0 pointer-events-none' : 'hover:ring-2 hover:ring-emerald-500/50'}`}
      title="Double-click to open"
      style={{
        left: item.position?.x ?? 0,
        top: item.position?.y ?? 0,
        width: DOC_ICON_SIZE,
        height: DOC_ICON_SIZE,
        minWidth: DOC_ICON_SIZE,
        minHeight: DOC_ICON_SIZE,
        maxWidth: DOC_ICON_SIZE,
        maxHeight: DOC_ICON_SIZE,
        backgroundColor: item.background_color ?? '#fef08a',
        borderTop: `3px solid ${item.header_color ?? '#eab308'}`,
      }}
    >
      <div className="flex justify-end absolute top-0 right-0 p-1 opacity-0 hover:opacity-100 transition-opacity z-10">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); e.preventDefault(); onDelete(item.id) }}
          className="p-1 rounded bg-red-500/80 text-white text-xs hover:bg-red-500"
          title="Delete"
        >
          ×
        </button>
      </div>
      <span className="text-2xl mb-1" title="Double-click to open">📓</span>
      <span className="text-xs font-medium text-slate-700 truncate w-full px-2 text-center" title={title}>
        {title}
      </span>
    </div>
  )
}

// ==================== CHECKLIST ====================

function useDebounce(fn, delay) {
  const timeoutRef = useRef(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  return useCallback((...args) => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => {
      fnRef.current(...args)
      timeoutRef.current = null
    }, delay)
  }, [delay])
}

function ChecklistNote({
  item,
  isSelected,
  onSelect,
  onUpdate,
  onDelete,
  onContentChange,
  onResizePreview,
  onMoveToFinished,
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `note-${item.id}`,
    data: { type: 'item', item },
  })
  const [localItems, setLocalItems] = useState(item.content?.items ?? [])
  useEffect(() => {
    setLocalItems(item.content?.items ?? [])
  }, [item.id, item.content?.items])
  const debouncedSave = useDebounce((items) => onContentChange({ items }), 400)

  const toggleItem = (idx) => {
    const next = localItems.map((it, i) => i === idx ? { ...it, checked: !it.checked } : it)
    setLocalItems(next)
    onContentChange({ items: next })
  }

  const updateItemText = (idx, text) => {
    const next = [...localItems]
    if (!next[idx]) next[idx] = { text: '', checked: false }
    next[idx] = { ...next[idx], text }
    setLocalItems(next)
    debouncedSave(next)
  }

  const addItem = () => {
    const next = [...localItems, { text: '', checked: false }]
    setLocalItems(next)
    onContentChange({ items: next })
  }

  const removeItem = (idx) => {
    const next = localItems.filter((_, i) => i !== idx)
    setLocalItems(next)
    onContentChange({ items: next })
  }

  // Filter drag listeners so resize handle doesn't trigger drag
  const dragListeners = useMemo(() => {
    const skip = (e) => e.target?.closest('[data-resize-handle]')
    return Object.fromEntries(
      Object.entries(listeners).map(([k, v]) => [
        k,
        typeof v === 'function' ? (e) => { if (!skip(e)) v(e) } : v,
      ])
    )
  }, [listeners])

  return (
    <div
      ref={setNodeRef}
      {...attributes}
      className={`absolute rounded-lg shadow-lg overflow-hidden transition-shadow flex flex-col ${
        isSelected ? 'ring-2 ring-emerald-500 ring-offset-2 ring-offset-slate-900' : ''
      } ${isDragging ? 'opacity-0 pointer-events-none' : ''}`}
      style={{
        left: item.position?.x ?? 0,
        top: item.position?.y ?? 0,
        width: item.size?.width ?? 220,
        height: item.size?.height ?? 200,
        backgroundColor: item.background_color,
        ...(item.content?.show_header === true && { borderTop: `4px solid ${item.header_color}` }),
      }}
      onClick={(e) => {
        e.stopPropagation()
        onSelect(item, e)
      }}
    >
      {/* Drag handle: top bar only — delete button top-right, invisible until hover */}
      <div
        {...dragListeners}
        className="group flex justify-end gap-1 p-1 h-7 flex-shrink-0 cursor-grab active:cursor-grabbing hover:bg-black/5 rounded-t-lg transition-colors"
        data-drag-handle
      >
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(item.id) }}
          className="p-1 rounded bg-red-500/80 text-white text-xs hover:bg-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
          title="Delete (user only)"
        >
          ×
        </button>
      </div>
      {/* Milanote-style title header */}
      {item.content?.show_title === true && (
        <div
          className="flex-shrink-0 px-3 py-2.5"
          style={{
            backgroundColor: item.content?.show_header === true ? `${item.header_color}12` : 'rgba(0,0,0,0.04)',
            borderBottom: '1px solid rgba(0,0,0,0.06)',
            textAlign: item.content?.title_align || 'left',
          }}
        >
          <input
            type="text"
            value={item.content?.title ?? ''}
            onChange={(e) => onContentChange({ title: e.target.value })}
            onClick={(e) => { e.stopPropagation(); onSelect(item) }}
            placeholder="Add a title..."
            className="w-full bg-transparent border-none outline-none text-[15px] font-medium text-slate-800 placeholder:text-slate-400/80 focus:ring-0 p-0 tracking-tight"
            style={{ textAlign: item.content?.title_align || 'left' }}
          />
        </div>
      )}
      <div className="p-3 overflow-auto flex-1 min-h-0">
        {localItems.map((it, idx) => (
          <div key={idx} className="flex items-center gap-2 mb-2 group">
            <input
              type="checkbox"
              checked={it.checked}
              onChange={() => toggleItem(idx)}
              className="rounded border-slate-600 text-emerald-600 focus:ring-emerald-500/50"
            />
            <input
              type="text"
              value={it.text}
              onChange={(e) => updateItemText(idx, e.target.value)}
              onClick={(e) => { e.stopPropagation(); onSelect(item, e) }}
              className={`flex-1 bg-transparent border-none outline-none text-sm text-slate-800 ${
                it.checked ? 'line-through text-slate-500' : ''
              }`}
              placeholder="Item..."
            />
            {it.checked ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  setLocalItems((prev) => prev.filter((_, i) => i !== idx))
                  onMoveToFinished?.(idx, it, item.id)
                }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-500 hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors"
                title="Move to finished"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              </button>
            ) : (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); removeItem(idx) }}
                className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 text-xs"
              >
                ×
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onSelect(item, e); addItem() }}
          className="text-xs text-slate-500 hover:text-emerald-400 mt-1"
        >
          + Add item
        </button>
      </div>
      {/* Resize handles — all four corners */}
      {(['se', 'sw', 'nw']).map((corner) => {
        const pos = { se: 'bottom-0 right-0', sw: 'bottom-0 left-0', ne: 'top-0 right-0', nw: 'top-0 left-0' }[corner]
        const cursor = { se: 'cursor-se-resize', sw: 'cursor-sw-resize', ne: 'cursor-ne-resize', nw: 'cursor-nw-resize' }[corner]
        const rounded = { se: 'rounded-tl', sw: 'rounded-tr', ne: 'rounded-bl', nw: 'rounded-br' }[corner]
        const flex = { se: 'items-end justify-end', sw: 'items-end justify-start', ne: 'items-start justify-end', nw: 'items-start justify-start' }[corner]
        const handleResize = (u) => onResizePreview ? onResizePreview(item.id, u) : onUpdate(item.id, u)
        const handleResizeEnd = (u) => onUpdate(item.id, u)
        return (
          <div
            key={corner}
            data-resize-handle
            onMouseDown={getResizeHandler(item, handleResize, handleResizeEnd, corner)}
            className={`absolute w-5 h-5 ${pos} ${cursor} hover:bg-black/10 ${rounded} flex ${flex} p-0.5`}
            title="Resize"
          >
            <span className="text-slate-500/60 text-[10px] font-mono">⋰</span>
          </div>
        )
      })}
    </div>
  )
}

// Resize handle — corner: 'se'|'sw'|'ne'|'nw'. onResize for live UI, onResizeEnd for API (mouseup only)
function getResizeHandler(item, onResize, onResizeEnd, corner = 'se') {
  const persist = onResizeEnd ?? onResize
  const minW = 120
  const minH = 80
  return (e) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startY = e.clientY
    const startW = item.size?.width ?? 200
    const startH = item.size?.height ?? 180
    const startLeft = item.position?.x ?? 0
    const startTop = item.position?.y ?? 0
    let lastUpdate = {}
    let rafId = null
    const onMove = (ev) => {
      const dx = ev.clientX - startX
      const dy = ev.clientY - startY
      let w, h, left, top
      switch (corner) {
        case 'se':
          w = Math.max(minW, Math.round(startW + dx))
          h = Math.max(minH, Math.round(startH + dy))
          lastUpdate = { size: { width: w, height: h } }
          break
        case 'sw':
          w = Math.max(minW, Math.round(startW - dx))
          h = Math.max(minH, Math.round(startH + dy))
          left = startLeft + (startW - w)
          lastUpdate = { position: { x: left, y: startTop }, size: { width: w, height: h } }
          break
        case 'ne':
          w = Math.max(minW, Math.round(startW + dx))
          h = Math.max(minH, Math.round(startH - dy))
          top = startTop + (startH - h)
          lastUpdate = { position: { x: startLeft, y: top }, size: { width: w, height: h } }
          break
        case 'nw':
          w = Math.max(minW, Math.round(startW - dx))
          h = Math.max(minH, Math.round(startH - dy))
          left = startLeft + (startW - w)
          top = startTop + (startH - h)
          lastUpdate = { position: { x: left, y: top }, size: { width: w, height: h } }
          break
        default:
          lastUpdate = { size: { width: Math.max(minW, startW + dx), height: Math.max(minH, startH + dy) } }
      }
      if (rafId) cancelAnimationFrame(rafId)
      rafId = requestAnimationFrame(() => {
        onResize(lastUpdate)
        rafId = null
      })
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      if (rafId) cancelAnimationFrame(rafId)
      onResize(lastUpdate)
      persist(lastUpdate)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }
}

// ==================== FINISHED PANEL ====================

function FinishedPanel({ items, onArchive }) {
  return (
    <div className="space-y-3">
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Finished items</p>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">No completed items yet.</p>
      ) : (
        <div className="space-y-1 max-h-64 overflow-auto">
          {items.map((f) => (
            <div
              key={f.id}
              className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-slate-700/50 group"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-300 line-through truncate">{f.text}</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  {f.finished_at ? new Date(f.finished_at).toLocaleString() : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onArchive(f.id)}
                className="p-1.5 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                title="Archive (remove from view, keep record)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ==================== BOARD APPEARANCE ====================

function BoardAppearancePanel({ boardId, settings, onChange }) {
  if (!boardId) return null
  const { gridEnabled, gridSize, backgroundColor } = settings

  return (
    <div className="space-y-4">
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Board appearance</p>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={gridEnabled}
          onChange={(e) => onChange({ gridEnabled: e.target.checked })}
          className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50"
        />
        <span className="text-sm text-slate-300">Show grid</span>
      </label>
      {gridEnabled && (
        <div>
          <p className="text-xs text-slate-500 mb-1">Grid size</p>
          <select
            value={gridSize}
            onChange={(e) => onChange({ gridSize: Number(e.target.value) })}
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-200"
          >
            {[12, 16, 20, 24, 32, 40].map((s) => (
              <option key={s} value={s}>{s}px</option>
            ))}
          </select>
        </div>
      )}
      <div>
        <p className="text-xs text-slate-500 mb-2">Background</p>
        <div className="space-y-2">
          {Object.entries(notesApi.BOARD_PRESETS).map(([key, items]) => (
            <div key={key}>
              <p className="text-xs text-slate-600 mb-1">
                {key === 'cream' ? 'Cream' : key === 'bold' ? 'Bold' : key === 'darkMode' ? 'Dark mode' : key === 'lightMode' ? 'Light mode' : 'Pastel'}
              </p>
              <div className="flex flex-wrap gap-1">
                {items.map(({ name, color }) => (
                  <button
                    key={color}
                    type="button"
                    onClick={() => onChange({ backgroundColor: color })}
                    className={`w-6 h-6 rounded border transition-transform hover:scale-110 ${
                      backgroundColor === color ? 'ring-2 ring-emerald-400 ring-offset-2 ring-offset-slate-900' : 'border-slate-600'
                    }`}
                    style={{ backgroundColor: color }}
                    title={name}
                  />
                ))}
              </div>
            </div>
          ))}
          <div className="pt-2">
            <p className="text-xs text-slate-500 mb-1">Custom</p>
            <input
              type="color"
              value={backgroundColor}
              onChange={(e) => onChange({ backgroundColor: e.target.value })}
              className="w-full h-8 rounded cursor-pointer bg-slate-800 border border-slate-700"
            />
          </div>
        </div>
      </div>
    </div>
  )
}

// ==================== NOTES AI PANEL ====================

function NotesAIPanel({
  activeBoardId,
  aiLoading,
  aiResult,
  recallQuery,
  setRecallQuery,
  onSummarize,
  onOrganize,
  onRecall,
}) {
  const isTestMode = notesApi.isTestMode()
  return (
    <div className="space-y-4">
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">AI tools</p>
      {isTestMode && (
        <p className="text-xs text-amber-400/90">AI tools require the backend. Switch off test mode (?test=1) to use.</p>
      )}
      <p className="text-xs text-slate-500">Use the agent to summarize, recall memories, or suggest organization.</p>
      <div className="space-y-2">
        <button
          type="button"
          onClick={onSummarize}
          disabled={isTestMode || !activeBoardId || aiLoading}
          className="w-full px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Summarize board
        </button>
        <button
          type="button"
          onClick={onOrganize}
          disabled={isTestMode || !activeBoardId || aiLoading}
          className="w-full px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          Organize
        </button>
        <div>
          <input
            type="text"
            value={recallQuery}
            onChange={(e) => setRecallQuery(e.target.value)}
            placeholder="Recall memories..."
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 mb-2"
          />
          <button
            type="button"
            onClick={onRecall}
            disabled={isTestMode || aiLoading}
            className="w-full px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Recall (Hindsight)
          </button>
        </div>
      </div>
      {aiLoading && <p className="text-xs text-slate-500">Thinking...</p>}
      {aiResult && (
        <div className="mt-4 p-3 rounded-lg bg-slate-800/80 border border-slate-700">
          <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
            {aiResult.type === 'summary' ? 'Summary' : aiResult.type === 'organize' ? 'Organization' : 'Recall'}
          </p>
          <div className="text-sm text-slate-300 whitespace-pre-wrap max-h-64 overflow-auto">
            {aiResult.text}
          </div>
        </div>
      )}
    </div>
  )
}

// ==================== NOTES EMPTY STATE ====================

function NotesEmptyState({ onAdd }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
      <div className="text-center pointer-events-auto">
        <p className="text-slate-500 text-sm mb-2">This board is empty</p>
        <p className="text-slate-600 text-xs mb-4">Add a note or checklist from the sidebar</p>
        <div className="flex gap-2 justify-center">
          <button
            type="button"
            onClick={() => onAdd('note', '#fef08a', '#eab308')}
            className="px-3 py-2 rounded-lg bg-slate-800 text-slate-300 text-sm hover:bg-slate-700 transition-colors"
          >
            + Note
          </button>
          <button
            type="button"
            onClick={() => onAdd('checklist', '#bbf7d0', '#22c55e')}
            className="px-3 py-2 rounded-lg bg-slate-800 text-slate-300 text-sm hover:bg-slate-700 transition-colors"
          >
            + Checklist
          </button>
        </div>
      </div>
    </div>
  )
}

// ==================== NOTES TAB ====================

export default function NotesTab() {
  const [boards, setBoards] = useState([])
  const [activeBoardId, setActiveBoardId] = useState(null)
  const [items, setItems] = useState([])
  const [finishedItems, setFinishedItems] = useState([])
  const [sidebarTab, setSidebarTab] = useState('style')
  const [aiResult, setAiResult] = useState(null)
  const [aiLoading, setAiLoading] = useState(false)
  const [recallQuery, setRecallQuery] = useState('')
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [boardSettings, setBoardSettings] = useState(notesApi.getBoardSettings(null))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedItem, setSelectedItem] = useState(null)
  const lastSelectedIdRef = useRef(null)
  const [editingBoardId, setEditingBoardId] = useState(null)
  const [newBoardName, setNewBoardName] = useState('')
  const [activeDragId, setActiveDragId] = useState(null)
  const [activeDragData, setActiveDragData] = useState(null)
  const [expandedDocId, setExpandedDocId] = useState(null)
  const [copyFeedback, setCopyFeedback] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [boardZoom, setBoardZoom] = useState(1)
  const [boardPan, setBoardPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const panStartRef = useRef(null)
  const didPanRef = useRef(false)
  const selectedEditorRef = useRef(null)
  const canvasRef = useRef(null)
  const lastDragCanvasPosRef = useRef(null)

  const loadBoards = useCallback(async () => {
    try {
      const data = await notesApi.getBoards()
      setBoards(data.boards || [])
      if (data.boards?.length && !activeBoardId) {
        setActiveBoardId(data.boards[0].id)
      }
    } catch (err) {
      setError(err.message)
    }
  }, [activeBoardId])

  const loadItems = useCallback(async () => {
    if (!activeBoardId) return
    try {
      const data = await notesApi.getItems(activeBoardId)
      setItems(data.items || [])
    } catch (err) {
      setError(err.message)
    }
  }, [activeBoardId])

  const loadFinishedItems = useCallback(async () => {
    if (!activeBoardId) return
    try {
      const items = await notesApi.getFinishedItems(activeBoardId)
      setFinishedItems(items)
    } catch (err) {
      setError(err.message)
    }
  }, [activeBoardId])

  useEffect(() => {
    loadBoards()
  }, [])

  useEffect(() => {
    if (activeBoardId) {
      loadItems()
      loadFinishedItems()
      setBoardSettings(notesApi.getBoardSettings(activeBoardId))
    } else {
      setItems([])
      setFinishedItems([])
    }
  }, [activeBoardId, loadItems, loadFinishedItems])

  const updateBoardSettings = (patch) => {
    if (!activeBoardId) return
    const next = { ...boardSettings, ...patch }
    setBoardSettings(next)
    notesApi.setBoardSettings(activeBoardId, next)
  }

  const convertToDoc = async (item) => {
    try {
      const content = { ...item.content, show_title: true, title: (item.content?.title ?? '').trim() || 'Untitled doc' }
      if (content.markdown) content.html = markdownToHtml(content.markdown)
      const updated = await notesApi.updateItem(item.id, {
        item_type: 'doc',
        content,
        size: { width: DOC_ICON_SIZE, height: DOC_ICON_SIZE },
      })
      setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, ...updated } : i)))
      setSelectedItem(null)
      setExpandedDocId(item.id)
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    if (boards.length > 0 || error) setLoading(false)
  }, [boards, error])

  const addItem = async (type, bgColor = BG_COLORS[0], headerColor = HEADER_COLORS[0], dropPosition) => {
    if (!type || !activeBoardId) return
    const pos = dropPosition ?? { x: 40 + items.length * 30, y: 40 + items.length * 30 }
    try {
      const item = await notesApi.createItem(activeBoardId, {
        item_type: type,
        content: type === 'note'
          ? { html: '', title: '', show_title: false, show_header: false }
          : { items: [], title: '', show_title: false, show_header: false },
        position: pos,
        size: { width: 192, height: 144 },
        background_color: bgColor,
        header_color: headerColor,
      })
      setItems((prev) => [...prev, item])
      setSelectedItem(item)
    } catch (err) {
      setError(err.message)
    }
  }

  const updateItem = async (itemId, patch) => {
    setItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, ...patch } : i)))
    if (selectedItem?.id === itemId) setSelectedItem((s) => (s?.id === itemId ? { ...s, ...patch } : s))
    try {
      const updated = await notesApi.updateItem(itemId, patch)
      // Preserve our position/size for drag/resize — backend may round or return different precision
      const merged = patch.position != null || patch.size != null
        ? { ...updated, ...(patch.position != null && { position: patch.position }), ...(patch.size != null && { size: patch.size }) }
        : updated
      setItems((prev) => prev.map((i) => (i.id === itemId ? merged : i)))
      if (selectedItem?.id === itemId) setSelectedItem(merged)
    } catch (err) {
      setError(err.message)
      loadItems()
    }
  }

  const deleteItem = useCallback(async (itemId, options = {}) => {
    const skipConfirm = options.skipConfirm
    const item = items.find((i) => i.id === itemId)
    const isDoc = item?.item_type === 'doc'
    const label = isDoc ? 'doc' : 'item'
    if (!skipConfirm && !window.confirm(`Are you sure you want to delete this ${label}?`)) return
    try {
      await notesApi.deleteItem(itemId)
      setItems((prev) => prev.filter((i) => i.id !== itemId))
      setSelectedItem((s) => (s?.id === itemId ? null : s))
      setSelectedIds((prev) => {
        const next = new Set(prev)
        next.delete(itemId)
        return next
      })
      if (expandedDocId === itemId) setExpandedDocId(null)
    } catch (err) {
      setError(err.message)
    }
  }, [items, expandedDocId])

  const deleteItemsBulk = useCallback(async (itemIds) => {
    try {
      for (const id of itemIds) {
        await notesApi.deleteItem(id)
      }
      setItems((prev) => prev.filter((i) => !itemIds.includes(i.id)))
      setSelectedItem(null)
      setSelectedIds(new Set())
      if (itemIds.includes(expandedDocId)) setExpandedDocId(null)
    } catch (err) {
      setError(err.message)
    }
  }, [expandedDocId])

  const moveToFinished = async (checklistItemIdx, checklistItem, checklistId) => {
    if (!activeBoardId) return
    const checklist = items.find((i) => i.id === checklistId)
    if (!checklist?.content?.items) return
    const next = checklist.content.items.filter((_, i) => i !== checklistItemIdx)
    setItems((prev) => prev.map((i) => (i.id === checklistId ? { ...i, content: { ...i.content, items: next } } : i)))
    try {
      await notesApi.addFinishedItem(activeBoardId, { text: checklistItem.text, source_checklist_id: checklistId })
      await notesApi.updateItem(checklistId, { content: { ...checklist.content, items: next } })
      loadFinishedItems()
    } catch (err) {
      setError(err.message)
      setItems((prev) => prev.map((i) => (i.id === checklistId ? { ...i, content: { ...i.content, items: checklist.content.items } } : i)))
    }
  }

  const archiveFinished = async (finishedId) => {
    if (!activeBoardId) return
    try {
      await notesApi.archiveFinishedItem(activeBoardId, finishedId)
      setFinishedItems((prev) => prev.filter((f) => f.id !== finishedId))
    } catch (err) {
      setError(err.message)
    }
  }

  const createBoard = async () => {
    try {
      const board = await notesApi.createBoard({ name: 'New board' })
      setBoards((prev) => [...prev, board])
      setActiveBoardId(board.id)
      setEditingBoardId(board.id)
      setNewBoardName(board.name)
    } catch (err) {
      setError(err.message)
    }
  }

  const renameBoard = async (boardId, name) => {
    try {
      const updated = await notesApi.updateBoard(boardId, { name: name || 'Untitled' })
      setBoards((prev) => prev.map((b) => (b.id === boardId ? updated : b)))
      setEditingBoardId(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const deleteBoard = async (boardId) => {
    const board = boards.find((b) => b.id === boardId)
    if (!board || board.name === 'General' || board.name === 'Private') return
    if (boards.length <= 1) return
    if (!window.confirm('Are you sure you want to delete this board? All notes and checklists on it will be removed.')) return
    try {
      await notesApi.deleteBoard(boardId)
      setBoards((prev) => prev.filter((b) => b.id !== boardId))
      if (activeBoardId === boardId) {
        const next = boards.find((b) => b.id !== boardId)
        setActiveBoardId(next?.id ?? null)
      }
    } catch (err) {
      setError(err.message)
    }
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const { setNodeRef } = useDroppable({ id: 'canvas' })

  // Keyboard shortcuts: Delete (delete selected), Escape (deselect)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setSelectedItem(null)
        setSelectedIds(new Set())
        return
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const target = document.activeElement
        if (target?.isContentEditable || target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
        const idsToDelete = selectedIds.size > 0 ? [...selectedIds] : (selectedItem ? [selectedItem.id] : [])
        if (idsToDelete.length === 0) return
        const label = idsToDelete.length === 1 ? 'item' : `${idsToDelete.length} items`
        if (!window.confirm(`Delete ${label}?`)) return
        deleteItemsBulk(idsToDelete)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedItem, selectedIds, deleteItemsBulk])

  const handleSelectItem = useCallback((item, addToSelection = false) => {
    if (addToSelection) {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        if (next.has(item.id)) next.delete(item.id)
        else next.add(item.id)
        return next
      })
      setSelectedItem(item)
      lastSelectedIdRef.current = item.id
    } else {
      setSelectedIds(new Set([item.id]))
      setSelectedItem(item)
      lastSelectedIdRef.current = item.id
    }
  }, [])

  const handleDeselectAll = useCallback(() => {
    setSelectedItem(null)
    setSelectedIds(new Set())
  }, [])

  const deleteSelectedBulk = useCallback(async () => {
    const ids = selectedIds.size > 0 ? [...selectedIds] : (selectedItem ? [selectedItem.id] : [])
    if (ids.length === 0) return
    if (!window.confirm(`Delete ${ids.length} item(s)?`)) return
    await deleteItemsBulk(ids)
  }, [selectedIds, selectedItem, deleteItemsBulk])

  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return items
    const q = searchQuery.toLowerCase().trim()
    return items.filter((item) => {
      const title = (item.content?.title ?? '').toLowerCase()
      const html = (item.content?.html ?? '').toLowerCase().replace(/<[^>]+>/g, ' ')
      const markdown = (item.content?.markdown ?? '').toLowerCase()
      const checklistText = (item.content?.items ?? []).map((i) => (i?.text ?? '').toLowerCase()).join(' ')
      return title.includes(q) || html.includes(q) || markdown.includes(q) || checklistText.includes(q)
    })
  }, [items, searchQuery])

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={(e) => {
        setActiveDragId(e.active.id)
        setActiveDragData(e.active.data.current)
        lastDragCanvasPosRef.current = null
      }}
      onDragMove={(event) => {
        const { active, delta } = event
        const data = active.data.current
        if (data?.type === 'item' && delta) {
          const item = data.item
          const zoom = Math.max(0.25, boardZoom)
          const newX = (item.position?.x ?? 0) + delta.x / zoom
          const newY = (item.position?.y ?? 0) + delta.y / zoom
          lastDragCanvasPosRef.current = { x: newX, y: newY }
        }
      }}
      onDragEnd={(event) => {
        const { active, delta, over } = event
        setActiveDragId(null)
        setActiveDragData(null)
        const data = active.data.current
        if (data?.type?.startsWith('add-') && canvasRef.current) {
          const ev = event.activatorEvent ?? event.active?.activatorEvent
          const rect = canvasRef.current.getBoundingClientRect()
          let clientX = 0, clientY = 0
          if (ev && typeof ev === 'object' && 'clientX' in ev && 'clientY' in ev) {
            clientX = ev.clientX + (delta?.x ?? 0)
            clientY = ev.clientY + (delta?.y ?? 0)
          } else {
            clientX = rect.left + rect.width / 2
            clientY = rect.top + rect.height / 2
          }
          const isOverCanvas = clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom
          if (isOverCanvas || over?.id === 'canvas') {
            const itemType = data.itemType
            const bgColor = data.bgColor ?? BG_COLORS[0]
            const headerColor = data.headerColor ?? HEADER_COLORS[0]
            const w = 192, h = 144
            const grid = boardSettings.gridSize ?? 12
            const rawX = clientX - rect.left + canvasRef.current.scrollLeft - w / 2
            const rawY = clientY - rect.top + canvasRef.current.scrollTop - h / 2
            const x = Math.max(0, Math.round(rawX / grid) * grid)
            const y = Math.max(0, Math.round(rawY / grid) * grid)
            addItem(itemType, bgColor, headerColor, { x, y })
            return
          }
        }
        if (data?.type === 'item') {
          const item = data.item
          // Prefer position from last onDragMove (more reliable); fallback to delta
          const pos = lastDragCanvasPosRef.current ?? (delta && (() => {
            const zoom = Math.max(0.25, boardZoom)
            return { x: (item.position?.x ?? 0) + delta.x / zoom, y: (item.position?.y ?? 0) + delta.y / zoom }
          })())
          if (pos) {
            updateItem(item.id, { position: { x: pos.x, y: pos.y } })
          }
          lastDragCanvasPosRef.current = null
        }
      }}
      autoScroll={false}
    >
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800 flex-shrink-0 overflow-x-auto">
          <button
            type="button"
            onClick={() => setShowShortcuts(true)}
            className="text-xs text-slate-500 hover:text-slate-400 transition-colors flex-shrink-0"
            title="View keyboard shortcuts"
          >
            Shortcuts
          </button>
          <span className="text-slate-600 flex-shrink-0">|</span>
          {boards.map((b) => (
            <div key={b.id} className="flex items-center gap-1 flex-shrink-0">
              {editingBoardId === b.id ? (
                <input
                  type="text"
                  value={newBoardName}
                  onChange={(e) => setNewBoardName(e.target.value)}
                  onBlur={() => renameBoard(b.id, newBoardName)}
                  onKeyDown={(e) => { if (e.key === 'Enter') renameBoard(b.id, newBoardName) }}
                  autoFocus
                  className="px-2 py-1 rounded bg-slate-800 border border-slate-600 text-sm text-slate-100 w-28"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setActiveBoardId(b.id)}
                  onDoubleClick={() => { setEditingBoardId(b.id); setNewBoardName(b.name) }}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    activeBoardId === b.id ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                  }`}
                >
                  {b.name}
                </button>
              )}
              {boards.length > 1 && b.name !== 'General' && b.name !== 'Private' && (
                <button type="button" onClick={() => deleteBoard(b.id)} className="p-1 text-slate-500 hover:text-red-400 text-xs" title="Delete board">×</button>
              )}
            </div>
          ))}
          <button type="button" onClick={createBoard} className="px-3 py-1.5 rounded-lg text-sm text-slate-500 hover:text-emerald-400 hover:bg-slate-800 transition-colors">+ New</button>
        </div>
        <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800 flex-shrink-0">
          <input
            type="text"
            placeholder="Search notes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 max-w-xs rounded-lg bg-slate-800 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
          />
          {boardZoom !== 1 && (
            <span className="text-xs text-slate-500">{Math.round(boardZoom * 100)}%</span>
          )}
          <div className="flex gap-1">
            <button type="button" onClick={() => setBoardZoom((z) => Math.max(0.25, z - 0.25))} className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400" title="Zoom out">−</button>
            <button type="button" onClick={() => setBoardZoom((z) => Math.min(2, z + 0.25))} className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400" title="Zoom in">+</button>
            <button type="button" onClick={() => { setBoardZoom(1); setBoardPan({ x: 0, y: 0 }) }} className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 text-xs" title="Reset zoom">1:1</button>
          </div>
        </div>
        {selectedIds.size > 1 && (
          <div className="flex items-center gap-2 px-4 py-2 bg-slate-800/50 border-b border-slate-700 flex-shrink-0">
            <span className="text-sm text-slate-400">{selectedIds.size} selected</span>
            <button type="button" onClick={deleteSelectedBulk} className="px-3 py-1 rounded-lg text-sm bg-red-600/80 hover:bg-red-600 text-white">Delete</button>
            <button type="button" onClick={handleDeselectAll} className="px-3 py-1 rounded-lg text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700">Clear selection</button>
          </div>
        )}
        <div
          ref={(el) => { setNodeRef(el); canvasRef.current = el }}
          className="flex-1 overflow-auto relative"
          style={{
            backgroundColor: boardSettings.backgroundColor,
            ...(boardSettings.gridEnabled && {
              backgroundImage: 'radial-gradient(circle at 1px 1px, rgba(100,116,139,0.4) 1px, transparent 0)',
              backgroundSize: `${boardSettings.gridSize}px ${boardSettings.gridSize}px`,
            }),
            cursor: isPanning ? 'grabbing' : undefined,
          }}
          onClick={() => { if (!didPanRef.current) handleDeselectAll(); didPanRef.current = false }}
          onMouseDown={(e) => {
            didPanRef.current = false
            if (e.button === 1 || (e.button === 0 && e.altKey)) {
              e.preventDefault()
              setIsPanning(true)
              panStartRef.current = { x: e.clientX - boardPan.x, y: e.clientY - boardPan.y }
            }
          }}
          title="Alt+drag or middle-click to pan • Ctrl+scroll to zoom"
          onMouseMove={(e) => {
            if (isPanning && panStartRef.current) { didPanRef.current = true; setBoardPan({ x: e.clientX - panStartRef.current.x, y: e.clientY - panStartRef.current.y }) }
          }}
          onMouseUp={() => setIsPanning(false)}
          onMouseLeave={() => setIsPanning(false)}
          onWheel={(e) => {
            if (e.ctrlKey || e.metaKey) {
              e.preventDefault()
              const delta = e.deltaY > 0 ? -0.1 : 0.1
              setBoardZoom((z) => Math.max(0.25, Math.min(2, z + delta)))
            }
          }}
        >
          {expandedDocId && (() => {
            const docItem = items.find((i) => i.id === expandedDocId)
            return docItem ? (
              <DocExpandedOverlay
                item={docItem}
                onCollapse={(contentPatch) => {
                  const updates = { size: { width: DOC_ICON_SIZE, height: DOC_ICON_SIZE } }
                  if (contentPatch && Object.keys(contentPatch).length > 0) {
                    updates.content = { ...docItem.content, ...contentPatch }
                  }
                  updateItem(docItem.id, updates)
                  setExpandedDocId(null)
                }}
                onContentChange={(c) => updateItem(docItem.id, { content: { ...docItem.content, ...c } })}
              />
            ) : null
          })()}
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 z-10">
              <span className="text-slate-400 text-sm">Loading notes...</span>
            </div>
          )}
          <div
            className="notes-canvas-inner relative min-h-full w-full origin-top-left"
            style={{
              minWidth: 800,
              minHeight: 600,
              transform: `translate(${boardPan.x}px, ${boardPan.y}px) scale(${boardZoom})`,
            }}
          >
            {notesApi.isTestMode() && (
              <div className="absolute top-2 left-4 z-30 px-2 py-1 rounded bg-amber-900/60 text-amber-200 text-xs border border-amber-700/50">Test mode: data in browser</div>
            )}
            {activeBoardId && boards.find((b) => b.id === activeBoardId)?.name === 'Private' && (
              <div className="absolute top-2 left-1/2 -translate-x-1/2 z-20 text-slate-400 text-sm">
                The agent cannot see or search this tab.
              </div>
            )}
            {!loading && activeBoardId && items.length === 0 && <NotesEmptyState onAdd={addItem} />}
            {filteredItems.map((item) =>
              item.item_type === 'doc' ? (
                <DocNote
                  key={item.id}
                  item={item}
                  isExpanded={false}
                  isSelected={selectedIds.has(item.id) || selectedItem?.id === item.id}
                  onExpand={() => setExpandedDocId(item.id)}
                  onCollapse={() => setExpandedDocId(null)}
                  onSelect={(i, ev) => handleSelectItem(i, ev?.ctrlKey || ev?.metaKey)}
                  onUpdate={updateItem}
                  onDelete={deleteItem}
                  onContentChange={(c) => updateItem(item.id, { content: { ...item.content, ...c } })}
                />
              ) : item.item_type === 'note' ? (
                <StickyNote
                  key={item.id}
                  item={item}
                  isSelected={selectedIds.has(item.id) || selectedItem?.id === item.id}
                  onSelect={(i, ev) => handleSelectItem(i, ev?.ctrlKey || ev?.metaKey)}
                  onUpdate={updateItem}
                  onDelete={deleteItem}
                  onContentChange={(c) => updateItem(item.id, { content: { ...item.content, ...c } })}
                  onConvertToDoc={convertToDoc}
                  registerEditorRef={(ref) => { selectedEditorRef.current = ref }}
                  onResizePreview={(id, update) => setItems(prev => prev.map(i => i.id === id ? { ...i, ...update } : i))}
                />
              ) : (
                <ChecklistNote
                  key={item.id}
                  item={item}
                  isSelected={selectedIds.has(item.id) || selectedItem?.id === item.id}
                  onSelect={(i, ev) => handleSelectItem(i, ev?.ctrlKey || ev?.metaKey)}
                  onUpdate={updateItem}
                  onDelete={deleteItem}
                  onContentChange={(c) => updateItem(item.id, { content: { ...item.content, ...c } })}
                  onResizePreview={(id, update) => setItems(prev => prev.map(i => i.id === id ? { ...i, ...update } : i))}
                  onMoveToFinished={moveToFinished}
                />
              )
            )}
          </div>
          <DragOverlay dropAnimation={null}>
            {activeDragId ? (() => {
              const item = items.find((i) => `note-${i.id}` === activeDragId)
              if (item) {
                if (item.item_type === 'doc') {
                  const title = (item.content?.title ?? '').trim() || 'Untitled doc'
                  return (
                    <div className="rounded-lg shadow-xl p-3 w-20 h-20 flex flex-col items-center justify-center cursor-grabbing" style={{ backgroundColor: item.background_color ?? '#fef08a' }}>
                      <span className="text-2xl">📓</span>
                      <span className="text-xs font-medium text-slate-700 truncate w-full text-center">{title}</span>
                    </div>
                  )
                }
                return <NoteDragPreview item={item} />
              }
              const bg = activeDragData?.bgColor ?? '#fef08a'
              if (activeDragId === 'add-note') return <div className="rounded-lg shadow-xl p-3 w-48 h-36 cursor-grabbing" style={{ backgroundColor: bg }}><span className="text-sm font-medium text-slate-800">Note</span></div>
              if (activeDragId === 'add-checklist') return <div className="rounded-lg shadow-xl p-3 w-48 h-36 cursor-grabbing" style={{ backgroundColor: bg }}><span className="text-sm font-medium text-slate-800">Checklist</span></div>
              return null
            })() : null}
          </DragOverlay>
        </div>
        </div>
      </div>
      <aside className="w-64 border-l border-slate-800 bg-slate-900/80 flex-shrink-0 overflow-y-auto p-4">
        {error && (
          <div className="mb-3 p-2 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">{error}</p>
            <button type="button" onClick={() => setError(null)} className="text-xs text-slate-500 hover:text-slate-300 mt-1">Dismiss</button>
          </div>
        )}
        {activeBoardId && (
          <div className="mb-4 pb-4 border-b border-slate-700">
            <BoardAppearancePanel boardId={activeBoardId} settings={boardSettings} onChange={updateBoardSettings} />
          </div>
        )}
        <div className="flex gap-1 mb-4 flex-wrap">
          <button type="button" onClick={() => setSidebarTab('style')} className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${sidebarTab === 'style' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'}`}>Style</button>
          <button type="button" onClick={() => setSidebarTab('finished')} className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${sidebarTab === 'finished' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'}`}>
            Finished {finishedItems.length > 0 && <span className="text-xs bg-emerald-700/50 px-1.5 py-0.5 rounded-full">{finishedItems.length}</span>}
          </button>
          <button type="button" onClick={() => { setSidebarTab('ai'); setAiResult(null) }} className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${sidebarTab === 'ai' ? 'bg-emerald-600 text-white' : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'}`}>AI</button>
        </div>
        {sidebarTab === 'ai' ? (
          <NotesAIPanel
            activeBoardId={activeBoardId}
            aiLoading={aiLoading}
            aiResult={aiResult}
            recallQuery={recallQuery}
            setRecallQuery={setRecallQuery}
            onSummarize={async () => {
              if (!activeBoardId) return
              setAiLoading(true)
              setAiResult(null)
              try {
                const data = await notesApi.summarizeBoard(activeBoardId)
                setAiResult({ type: 'summary', text: data.summary })
              } catch (err) {
                setError(err.message)
              } finally {
                setAiLoading(false)
              }
            }}
            onOrganize={async () => {
              if (!activeBoardId) return
              setAiLoading(true)
              setAiResult(null)
              try {
                const data = await notesApi.organizeBoard(activeBoardId)
                setAiResult({ type: 'organize', text: data.suggestions })
              } catch (err) {
                setError(err.message)
              } finally {
                setAiLoading(false)
              }
            }}
            onRecall={async () => {
              setAiLoading(true)
              setAiResult(null)
              try {
                const data = await notesApi.hindsightRecall(recallQuery || 'recent memories')
                setAiResult({ type: 'recall', text: data.results })
              } catch (err) {
                setError(err.message)
              } finally {
                setAiLoading(false)
              }
            }}
          />
        ) : sidebarTab === 'finished' ? (
          <FinishedPanel items={finishedItems} onArchive={archiveFinished} />
        ) : selectedItem && selectedItem.item_type === 'doc' ? (
          <div className="space-y-4">
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Doc</p>
            <p className="text-xs text-slate-500 mb-1">Name</p>
            <input
              type="text"
              value={selectedItem.content?.title ?? ''}
              onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, title: e.target.value } })}
              placeholder="Untitled doc"
              className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
            />
            <p className="text-xs text-slate-500">Double-click the doc on the board to open and edit.</p>
          </div>
        ) : selectedItem && selectedItem.item_type === 'note' ? (
          <>
            <div className="mb-4">
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input type="checkbox" checked={selectedItem.content?.show_title === true} onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, show_title: e.target.checked } })} className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50" />
                <span className="text-sm text-slate-300">Show title</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input type="checkbox" checked={selectedItem.content?.show_header === true} onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, show_header: e.target.checked } })} className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50" />
                <span className="text-sm text-slate-300">Show header bar</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input
                  type="checkbox"
                  checked={selectedItem.content?.use_markdown === true}
                  onChange={(e) => {
                    const on = e.target.checked
                    const content = { ...selectedItem.content, use_markdown: on }
                    if (on && !content.markdown) content.markdown = stripHtml(selectedItem.content?.html ?? '')
                    updateItem(selectedItem.id, { content })
                  }}
                  className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50"
                />
                <span className="text-sm text-slate-300">Markdown</span>
              </label>
              {selectedItem.content?.show_title === true && (
                <>
                  <p className="text-xs text-slate-500 mb-1">Title</p>
                  <input type="text" value={selectedItem.content?.title ?? ''} onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, title: e.target.value } })} placeholder="Add a title..." className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-medium text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 mb-2" />
                  <p className="text-xs text-slate-500 mb-1">Title alignment</p>
                  <div className="flex gap-1">
                    {['left', 'center', 'right'].map((align) => (
                      <button key={align} type="button" onClick={() => updateItem(selectedItem.id, { content: { ...selectedItem.content, title_align: align } })} className={`flex-1 px-2 py-1.5 rounded text-xs font-medium transition-colors ${(selectedItem.content?.title_align || 'left') === align ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-700'}`}>{align === 'left' ? 'Left' : align === 'center' ? 'Center' : 'Right'}</button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <StylingToolbar
              editorRef={selectedEditorRef}
              selectedColor="#000000"
              useMarkdown={selectedItem.content?.use_markdown === true}
              onCopyNote={async () => {
                const text = (selectedItem.content?.use_markdown
                  ? (selectedItem.content?.markdown ?? '').trim()
                  : stripHtml(selectedItem.content?.html ?? '').trim())
                if (text) {
                  try {
                    await navigator.clipboard.writeText(text)
                    setCopyFeedback(true)
                    setTimeout(() => setCopyFeedback(false), 1500)
                  } catch {
                    setError('Copy failed')
                  }
                }
              }}
              copyFeedback={copyFeedback}
            />
            <div className="mt-6 pt-4 border-t border-slate-700">
              <p className="text-xs text-slate-500 mb-2">Note colors</p>
              <div className="flex flex-wrap gap-1 mb-2">
                {BG_COLORS.map((c) => (
                  <button key={c} type="button" onClick={() => updateItem(selectedItem.id, { background_color: c })} className={`w-6 h-6 rounded border ${selectedItem.background_color === c ? 'border-white ring-1 ring-white' : 'border-slate-600'}`} style={{ backgroundColor: c }} />
                ))}
              </div>
              <div className="mt-2">
                <p className="text-xs text-slate-500 mb-1">Custom</p>
                <input type="color" value={selectedItem.background_color || '#ffffff'} onChange={(e) => updateItem(selectedItem.id, { background_color: e.target.value })} className="w-full h-8 rounded cursor-pointer bg-slate-800 border border-slate-700" />
              </div>
              <div className="mt-2">
                <p className="text-xs text-slate-500 mb-1">Header</p>
                <div className="flex flex-wrap gap-1">
                  {HEADER_COLORS.map((c) => (
                    <button key={c} type="button" onClick={() => updateItem(selectedItem.id, { header_color: c })} className={`w-6 h-6 rounded border ${selectedItem.header_color === c ? 'border-white ring-1 ring-white' : 'border-slate-600'}`} style={{ backgroundColor: c }} />
                  ))}
                </div>
              </div>
            </div>
          </>
        ) : selectedItem && selectedItem.item_type === 'checklist' ? (
          <div className="space-y-4">
            <div className="mb-4">
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input type="checkbox" checked={selectedItem.content?.show_title === true} onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, show_title: e.target.checked } })} className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50" />
                <span className="text-sm text-slate-300">Show title</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer mb-2">
                <input type="checkbox" checked={selectedItem.content?.show_header === true} onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, show_header: e.target.checked } })} className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50" />
                <span className="text-sm text-slate-300">Show header bar</span>
              </label>
              {selectedItem.content?.show_title === true && (
                <>
                  <p className="text-xs text-slate-500 mb-1">Title</p>
                  <input type="text" value={selectedItem.content?.title ?? ''} onChange={(e) => updateItem(selectedItem.id, { content: { ...selectedItem.content, title: e.target.value } })} placeholder="Add a title..." className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm font-medium text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 mb-2" />
                  <p className="text-xs text-slate-500 mb-1">Title alignment</p>
                  <div className="flex gap-1">
                    {['left', 'center', 'right'].map((align) => (
                      <button key={align} type="button" onClick={() => updateItem(selectedItem.id, { content: { ...selectedItem.content, title_align: align } })} className={`flex-1 px-2 py-1.5 rounded text-xs font-medium transition-colors ${(selectedItem.content?.title_align || 'left') === align ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-700'}`}>{align === 'left' ? 'Left' : align === 'center' ? 'Center' : 'Right'}</button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">Checklist colors</p>
            <div>
              <p className="text-xs text-slate-500 mb-2">Background</p>
              <div className="flex flex-wrap gap-1">
                {BG_COLORS.map((c) => (
                  <button key={c} type="button" onClick={() => updateItem(selectedItem.id, { background_color: c })} className={`w-6 h-6 rounded border ${selectedItem.background_color === c ? 'border-white ring-1 ring-white' : 'border-slate-600'}`} style={{ backgroundColor: c }} />
                ))}
              </div>
              <div className="mt-2">
                <p className="text-xs text-slate-500 mb-1">Custom</p>
                <input type="color" value={selectedItem.background_color || '#ffffff'} onChange={(e) => updateItem(selectedItem.id, { background_color: e.target.value })} className="w-full h-8 rounded cursor-pointer bg-slate-800 border border-slate-700" />
              </div>
            </div>
            <div>
              <p className="text-xs text-slate-500 mb-2">Header</p>
              <div className="flex flex-wrap gap-1">
                {HEADER_COLORS.map((c) => (
                  <button key={c} type="button" onClick={() => updateItem(selectedItem.id, { header_color: c })} className={`w-6 h-6 rounded border ${selectedItem.header_color === c ? 'border-white ring-1 ring-white' : 'border-slate-600'}`} style={{ backgroundColor: c }} />
                ))}
              </div>
            </div>
          </div>
        ) : (
          <AddNotePalette onAdd={addItem} />
        )}
      </aside>
      {showShortcuts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowShortcuts(false)}>
          <div
            className="bg-slate-800 border border-slate-600 rounded-xl shadow-xl max-w-md w-full mx-4 max-h-[80vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-5">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-slate-100">Notes shortcuts</h3>
                <button type="button" onClick={() => setShowShortcuts(false)} className="text-slate-400 hover:text-slate-200 p-1">×</button>
              </div>
              <p className="text-xs text-slate-500 mb-4">Keyboard shortcuts and interactions for the Notes board.</p>
              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="font-medium text-slate-300">Escape</dt>
                  <dd className="text-slate-400 ml-0">Deselect all</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Delete / Backspace</dt>
                  <dd className="text-slate-400 ml-0">Delete selected item(s). Skips when typing in a note.</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Ctrl+click (or Cmd+click)</dt>
                  <dd className="text-slate-400 ml-0">Add or remove items from multi-select</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Alt+drag or middle-click + drag</dt>
                  <dd className="text-slate-400 ml-0">Pan the board</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Ctrl+scroll (or Cmd+scroll)</dt>
                  <dd className="text-slate-400 ml-0">Zoom in or out</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Drag from top bar</dt>
                  <dd className="text-slate-400 ml-0">Move a note. The rest of the note allows text selection.</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Resize handles</dt>
                  <dd className="text-slate-400 ml-0">Bottom-right, bottom-left, top-left corners. Top-right reserved for delete.</dd>
                </div>
                <div>
                  <dt className="font-medium text-slate-300">Search bar</dt>
                  <dd className="text-slate-400 ml-0">Filters notes by title, content, or checklist items</dd>
                </div>
              </dl>
            </div>
          </div>
        </div>
      )}
    </div>
    </DndContext>
  )
}

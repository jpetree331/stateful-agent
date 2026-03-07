import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import Picker from '@emoji-mart/react'
import emojiData from '@emoji-mart/data'
import NotesTab from './NotesTab'
import JournalTab from './JournalTab'

const API_BASE = '/api'

// Strip <actions><react emoji="X" /></actions> and replace with actual emoji
const EMOJI_MAP = { heart: '❤️', smile: '😊', thumbsup: '👍', wave: '👋', star: '⭐' }
function cleanAssistantContent(text) {
  if (!text || typeof text !== 'string') return text
  return text
    .replace(/<actions>\s*<react\s+emoji="(\w+)"\s*\/>\s*<\/actions>/gi, (_, name) => (EMOJI_MAP[name?.toLowerCase()] ?? '') + ' ')
    .replace(/<actions>[\s\S]*?<\/actions>/gi, '')
    .trim()
}

// Day names and helpers
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const DAY_FULL_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function formatDate(dateStr) {
  if (!dateStr) return 'Never'
  const date = new Date(dateStr)
  return date.toLocaleString()
}

// ==================== CRON TAB COMPONENTS ====================

// Calendar day picker component
function DayPicker({ selectedDays, onChange }) {
  const toggleDay = (day) => {
    if (selectedDays.includes(day)) {
      onChange(selectedDays.filter(d => d !== day))
    } else {
      onChange([...selectedDays, day].sort())
    }
  }

  const selectAll = () => onChange([0, 1, 2, 3, 4, 5, 6])
  const selectWeekdays = () => onChange([0, 1, 2, 3, 4])
  const selectWeekends = () => onChange([5, 6])
  const clearAll = () => onChange([])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {DAY_NAMES.map((name, idx) => (
          <button
            key={idx}
            onClick={() => toggleDay(idx)}
            className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
              selectedDays.includes(idx)
                ? 'bg-emerald-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
            title={DAY_FULL_NAMES[idx]}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <button onClick={selectAll} className="text-xs text-emerald-400 hover:text-emerald-300">
          All
        </button>
        <span className="text-slate-600">|</span>
        <button onClick={selectWeekdays} className="text-xs text-emerald-400 hover:text-emerald-300">
          Weekdays
        </button>
        <span className="text-slate-600">|</span>
        <button onClick={selectWeekends} className="text-xs text-emerald-400 hover:text-emerald-300">
          Weekends
        </button>
        <span className="text-slate-600">|</span>
        <button onClick={clearAll} className="text-xs text-red-400 hover:text-red-300">
          Clear
        </button>
      </div>
    </div>
  )
}

// Time input with AM/PM
function TimeInput({ value, onChange }) {
  const [time, setTime] = useState(value || '')
  const [isValid, setIsValid] = useState(true)

  const validateTime = (t) => {
    // Accept formats: "7:00 PM", "19:00", "7 PM", etc.
    const regex = /^(1[0-2]|0?[1-9]):?([0-5][0-9])?\s?(AM|PM|am|pm)?$/
    return regex.test(t.trim())
  }

  const handleChange = (e) => {
    const newTime = e.target.value
    setTime(newTime)
    setIsValid(validateTime(newTime))
    if (validateTime(newTime)) {
      onChange(newTime)
    }
  }

  return (
    <div className="relative">
      <input
        type="text"
        value={time}
        onChange={handleChange}
        placeholder="7:00 PM"
        className={`w-full rounded-lg bg-slate-800 border px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:border-transparent ${
          isValid 
            ? 'border-slate-700 focus:ring-emerald-500/50' 
            : 'border-red-500 focus:ring-red-500/50'
        }`}
      />
      {!isValid && (
        <p className="text-xs text-red-400 mt-1">Use format like "7:00 PM" or "19:00"</p>
      )}
    </div>
  )
}

// Cron job card (for the queue)
function CronJobCard({ job, onEdit, onPause, onResume, onClone, onDelete, onToggleLock }) {
  const [showConfirmDelete, setShowConfirmDelete] = useState(false)
  const [instructionsExpanded, setInstructionsExpanded] = useState(false)
  const [descriptionExpanded, setDescriptionExpanded] = useState(false)
  const [lockBusy, setLockBusy] = useState(false)

  const getStatusColor = (status) => {
    switch (status) {
      case 'active': return 'bg-emerald-500'
      case 'paused': return 'bg-amber-500'
      default: return 'bg-slate-500'
    }
  }

  const getLastRunStatusColor = (status) => {
    switch (status) {
      case 'success': return 'text-emerald-400'
      case 'error': return 'text-red-400'
      case 'skipped': return 'text-amber-400'
      case 'aborted': return 'text-red-500'
      default: return 'text-slate-400'
    }
  }

  const handleToggleLock = async () => {
    setLockBusy(true)
    try { await onToggleLock(job.id, !job.is_locked) }
    finally { setLockBusy(false) }
  }

  return (
    <div className={`bg-slate-800/50 border rounded-xl p-4 transition-colors ${job.is_locked ? 'border-amber-700/60 hover:border-amber-600/60' : 'border-slate-700/50 hover:border-slate-600/50'}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${getStatusColor(job.status)}`} />
          <h3 className="text-lg font-semibold text-slate-100">{job.name}</h3>
          {job.is_one_time && (
            <span className="text-xs bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded">One-time</span>
          )}
          {job.created_by === 'agent' && (
            <span className="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded">Agent</span>
          )}
          {job.is_locked && (
            <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded flex items-center gap-1">
              🔒 Locked
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {/* Lock toggle */}
          <button
            onClick={handleToggleLock}
            disabled={lockBusy}
            title={job.is_locked ? 'Unlock — allow AI to edit' : 'Lock — prevent AI edits'}
            className={`px-3 py-1.5 text-sm rounded-lg transition-colors disabled:opacity-50 ${
              job.is_locked
                ? 'bg-amber-600/30 text-amber-300 hover:bg-amber-600/50'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600 hover:text-slate-200'
            }`}
          >
            {lockBusy ? '…' : job.is_locked ? '🔒 Locked' : '🔓 Lock'}
          </button>

          {job.status === 'active' ? (
            <button
              onClick={() => onPause(job.id)}
              className="px-3 py-1.5 text-sm bg-amber-600/20 text-amber-300 rounded-lg hover:bg-amber-600/30 transition-colors"
            >
              Pause
            </button>
          ) : (
            <button
              onClick={() => onResume(job.id)}
              className="px-3 py-1.5 text-sm bg-emerald-600/20 text-emerald-300 rounded-lg hover:bg-emerald-600/30 transition-colors"
            >
              Resume
            </button>
          )}
          <button
            onClick={() => onEdit(job)}
            disabled={job.is_locked}
            title={job.is_locked ? 'Unlock to edit' : 'Edit'}
            className="px-3 py-1.5 text-sm bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Edit
          </button>
          <button
            onClick={() => onClone(job.id)}
            className="px-3 py-1.5 text-sm bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
          >
            Clone
          </button>
          {showConfirmDelete ? (
            <div className="flex items-center gap-2">
              <button
                onClick={() => onDelete(job.id)}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-500 transition-colors"
              >
                Confirm
              </button>
              <button
                onClick={() => setShowConfirmDelete(false)}
                className="px-3 py-1.5 text-sm bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowConfirmDelete(true)}
              disabled={job.is_locked}
              title={job.is_locked ? 'Unlock to delete' : 'Delete'}
              className="px-3 py-1.5 text-sm bg-red-600/20 text-red-300 rounded-lg hover:bg-red-600/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {/* Description */}
      {job.description && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-slate-500">Description:</span>
            {job.description.length > 100 && (
              <button
                type="button"
                onClick={() => setDescriptionExpanded((e) => !e)}
                className="text-xs text-emerald-400 hover:text-emerald-300"
              >
                {descriptionExpanded ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>
          <p className={`text-sm text-slate-400 ${descriptionExpanded ? '' : 'line-clamp-2'}`}>
            {job.description}
          </p>
        </div>
      )}

      {/* Instructions preview with expand */}
      <div className="bg-slate-900/50 rounded-lg p-3 mb-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs text-slate-500">Instructions:</p>
          {job.instructions && job.instructions.length > 120 && (
            <button
              type="button"
              onClick={() => setInstructionsExpanded((e) => !e)}
              className="text-xs text-emerald-400 hover:text-emerald-300"
            >
              {instructionsExpanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>
        <p className={`text-sm text-slate-300 whitespace-pre-wrap ${instructionsExpanded ? '' : 'line-clamp-3'}`}>
          {job.instructions}
        </p>
      </div>

      {/* Schedule info */}
      <div className="flex flex-wrap gap-4 text-sm mb-3">
        {job.schedule_time && (
          <div className="flex items-center gap-2">
            <span className="text-slate-500">Time:</span>
            <span className="text-slate-200">{job.schedule_time}</span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="text-slate-500">Timezone:</span>
          <span className="text-slate-200">{job.timezone_display}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-slate-500">{job.is_one_time ? 'Date:' : 'Days:'}</span>
          <span className="text-slate-200">{job.schedule_days_display}</span>
        </div>
      </div>

      {/* Stats panel */}
      <div className="border-t border-slate-700/50 pt-3 mt-3">
        <div className="grid grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-slate-500 text-xs mb-1">Status</p>
            <p className={`font-medium ${job.status === 'active' ? 'text-emerald-400' : 'text-amber-400'}`}>
              {job.status === 'active' ? 'Active' : 'Paused'}
            </p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-1">Last Run</p>
            <p className="text-slate-300">{formatDate(job.last_run_at)}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-1">Last Status</p>
            <p className={`font-medium ${getLastRunStatusColor(job.last_run_status)}`}>
              {job.last_run_status ? job.last_run_status.charAt(0).toUpperCase() + job.last_run_status.slice(1) : 'None'}
            </p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-1">Run Count</p>
            <p className="text-slate-300">{job.run_count || 0}</p>
          </div>
        </div>
        {job.last_run_error && (
          <div className="mt-3 p-2 bg-red-900/20 border border-red-800/50 rounded">
            <p className="text-xs text-red-400">Last Error:</p>
            <p className="text-xs text-red-300 font-mono mt-1 line-clamp-2">{job.last_run_error}</p>
          </div>
        )}
      </div>
    </div>
  )
}

// Main Cron Tab Component
function CronTab() {
  const [jobs, setJobs] = useState([])
  const [timezones, setTimezones] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  // Form state
  const [isEditing, setIsEditing] = useState(false)
  const [editJobId, setEditJobId] = useState(null)
  const [jobType, setJobType] = useState('recurring') // 'recurring' or 'one-time'
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    instructions: '',
    schedule_days: [0, 1, 2, 3, 4],
    schedule_time: '7:00 PM',
    timezone: 'America/New_York',
    run_date: '',
  })
  const [formError, setFormError] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Fetch jobs and timezones
  const fetchData = async () => {
    try {
      setLoading(true)
      setError(null)
      
      const [jobsRes, tzRes] = await Promise.all([
        fetch(`${API_BASE}/cron/jobs`),
        fetch(`${API_BASE}/cron/timezones`),
      ])
      
      if (!jobsRes.ok) throw new Error('Failed to fetch jobs')
      if (!tzRes.ok) throw new Error('Failed to fetch timezones')
      
      const jobsData = await jobsRes.json()
      const tzData = await tzRes.json()
      
      setJobs(jobsData.jobs || [])
      setTimezones(tzData.timezones || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    // No auto-refresh - user must click Refresh button
  }, [])

  const resetForm = () => {
    setJobType('recurring')
    setFormData({
      name: '',
      description: '',
      instructions: '',
      schedule_days: [0, 1, 2, 3, 4],
      schedule_time: '7:00 PM',
      timezone: 'America/New_York',
      run_date: '',
    })
    setFormError(null)
    setIsEditing(false)
    setEditJobId(null)
  }

  const handleEdit = (job) => {
    setJobType(job.is_one_time ? 'one-time' : 'recurring')
    setFormData({
      name: job.name,
      description: job.description || '',
      instructions: job.instructions,
      schedule_days: job.schedule_days || [0, 1, 2, 3, 4],
      schedule_time: job.schedule_time || '7:00 PM',
      timezone: job.timezone,
      run_date: job.run_date || '',
    })
    setIsEditing(true)
    setEditJobId(job.id)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setFormError(null)
    
    if (!formData.name.trim()) {
      setFormError('Name is required')
      return
    }
    if (!formData.instructions.trim()) {
      setFormError('Instructions are required')
      return
    }
    if (!formData.schedule_time.trim()) {
      setFormError('Time is required')
      return
    }
    
    // Build payload based on job type
    const payload = {
      name: formData.name,
      description: formData.description,
      instructions: formData.instructions,
      schedule_time: formData.schedule_time,
      timezone: formData.timezone,
    }
    
    if (jobType === 'one-time') {
      if (!formData.run_date) {
        setFormError('Date is required for one-time jobs')
        return
      }
      payload.run_date = formData.run_date
      payload.schedule_days = null
      // Reactivate when editing so the job gets re-scheduled
      if (isEditing) payload.status = 'active'
    } else {
      if (formData.schedule_days.length === 0) {
        setFormError('Select at least one day')
        return
      }
      payload.schedule_days = formData.schedule_days
      payload.run_date = null
    }
    
    setIsSubmitting(true)
    
    try {
      const url = isEditing 
        ? `${API_BASE}/cron/jobs/${editJobId}`
        : `${API_BASE}/cron/jobs`
      const method = isEditing ? 'PUT' : 'POST'
      
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      
      resetForm()
      fetchData()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handlePause = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/cron/jobs/${id}/pause`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to pause job')
      fetchData()
    } catch (err) {
      alert(err.message)
    }
  }

  const handleResume = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/cron/jobs/${id}/resume`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to resume job')
      fetchData()
    } catch (err) {
      alert(err.message)
    }
  }

  const handleClone = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/cron/jobs/${id}/clone`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to clone job')
      fetchData()
    } catch (err) {
      alert(err.message)
    }
  }

  const handleDelete = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/cron/jobs/${id}`, { method: 'DELETE' })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || 'Failed to delete job')
      }
      fetchData()
    } catch (err) {
      alert(err.message)
    }
  }

  const handleToggleLock = async (id, lock) => {
    try {
      const endpoint = lock ? 'lock' : 'unlock'
      const res = await fetch(`${API_BASE}/cron/jobs/${id}/${endpoint}`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to ${endpoint} job`)
      fetchData()
    } catch (err) {
      alert(err.message)
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">Cron Jobs</h2>
          <p className="text-sm text-slate-400 mt-1">
            Schedule automated tasks for your agent. Jobs run with full memory and context.
          </p>
        </div>
        <button
          onClick={fetchData}
          className="text-sm text-emerald-400 hover:text-emerald-300 px-3 py-1.5 rounded-lg border border-emerald-500/30 hover:border-emerald-500/50 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Job Creation/Edit Form */}
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">
          {isEditing ? 'Edit Cron Job' : 'Create New Cron Job'}
        </h3>
        
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Job Type Toggle */}
          {!isEditing && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Job Type
              </label>
              <div className="flex gap-2 p-1 bg-slate-900/50 rounded-lg w-fit">
                <button
                  type="button"
                  onClick={() => setJobType('recurring')}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                    jobType === 'recurring'
                      ? 'bg-emerald-600 text-white'
                      : 'text-slate-300 hover:text-slate-100'
                  }`}
                >
                  Recurring
                </button>
                <button
                  type="button"
                  onClick={() => setJobType('one-time')}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                    jobType === 'one-time'
                      ? 'bg-emerald-600 text-white'
                      : 'text-slate-300 hover:text-slate-100'
                  }`}
                >
                  One-time
                </button>
              </div>
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="Daily Reflection"
              className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Description (optional)
            </label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Brief description of what this job does"
              className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
            />
          </div>

          {/* Instructions */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Instructions <span className="text-red-400">*</span>
            </label>
            <textarea
              value={formData.instructions}
              onChange={(e) => setFormData({ ...formData, instructions: e.target.value })}
              placeholder="Write a reflection on today's conversations..."
              rows={4}
              className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50 resize-y"
            />
            <p className="text-xs text-slate-500 mt-1">
              These instructions will be sent to the agent when the job runs.
            </p>
          </div>

          {/* Schedule */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Timezone */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Timezone
              </label>
              <select
                value={formData.timezone}
                onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-4 py-2.5 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
              >
                {timezones.map((tz) => (
                  <option key={tz.value} value={tz.value}>
                    {tz.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Time */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Time <span className="text-red-400">*</span>
              </label>
              <TimeInput
                value={formData.schedule_time}
                onChange={(time) => setFormData({ ...formData, schedule_time: time })}
              />
            </div>
          </div>

          {/* Days or Date based on job type */}
          {jobType === 'one-time' ? (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Date <span className="text-red-400">*</span>
              </label>
              <input
                type="date"
                value={formData.run_date}
                onChange={(e) => setFormData({ ...formData, run_date: e.target.value })}
                min={new Date().toISOString().split('T')[0]}
                className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-4 py-2.5 text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
              />
              <p className="text-xs text-slate-500 mt-1">
                The job will run once on this date at the specified time.
              </p>
            </div>
          ) : (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Days <span className="text-red-400">*</span>
              </label>
              <DayPicker
                selectedDays={formData.schedule_days}
                onChange={(days) => setFormData({ ...formData, schedule_days: days })}
              />
            </div>
          )}

          {/* Error */}
          {formError && (
            <div className="p-3 bg-red-900/20 border border-red-800/50 rounded-lg">
              <p className="text-sm text-red-400">{formError}</p>
            </div>
          )}

          {/* Buttons */}
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2.5 bg-emerald-600 text-white font-medium rounded-lg hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isSubmitting ? 'Saving...' : (isEditing ? 'Update Job' : 'Create Job')}
            </button>
            {isEditing && (
              <button
                type="button"
                onClick={resetForm}
                className="px-5 py-2.5 bg-slate-700 text-slate-300 font-medium rounded-lg hover:bg-slate-600 transition-colors"
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      </div>

      {/* Jobs Queue */}
      <div>
        <h3 className="text-lg font-semibold text-slate-100 mb-4">
          Job Queue ({jobs.length})
        </h3>
        
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <span className="text-slate-400">Loading jobs...</span>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-32">
            <div className="text-center">
              <p className="text-red-400 mb-2">{error}</p>
              <button
                onClick={fetchData}
                className="text-emerald-400 hover:text-emerald-300 text-sm"
              >
                Retry
              </button>
            </div>
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-12 bg-slate-800/30 rounded-xl border border-dashed border-slate-700">
            <p className="text-slate-400">No cron jobs yet.</p>
            <p className="text-slate-500 text-sm mt-1">Create your first job above.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {jobs.map((job) => (
              <CronJobCard
                key={job.id}
                job={job}
                onEdit={handleEdit}
                onPause={handlePause}
                onResume={handleResume}
                onClone={handleClone}
                onDelete={handleDelete}
                onToggleLock={handleToggleLock}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== DATA TAB (Knowledge Bank) ====================

function DataTab() {
  const [files, setFiles] = useState([])
  const [configured, setConfigured] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [expandedId, setExpandedId] = useState(null)
  const [chunks, setChunks] = useState({})
  const [searchQuery, setSearchQuery] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [editingTagsId, setEditingTagsId] = useState(null)
  const [editingTags, setEditingTags] = useState('')
  const fileInputRef = useRef(null)

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/status`)
      const data = await res.json()
      setConfigured(data.configured || false)
      return data.configured
    } catch {
      setConfigured(false)
      return false
    }
  }

  const fetchFiles = async () => {
    try {
      setLoading(true)
      setError(null)
      const ok = await fetchStatus()
      if (!ok) {
        setFiles([])
        setError('Knowledge Bank not configured. Set KNOWLEDGE_DATABASE_URL in .env')
        return
      }
      const url = searchQuery.trim()
        ? `${API_BASE}/knowledge/files?search=${encodeURIComponent(searchQuery.trim())}`
        : `${API_BASE}/knowledge/files`
      const res = await fetch(url)
      if (!res.ok) throw new Error('Failed to fetch files')
      const data = await res.json()
      setFiles(data.files || [])
    } catch (err) {
      setError(err.message)
      setFiles([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchFiles()
  }, [searchQuery])

  const handleUpload = async (e) => {
    const selectedFiles = e?.target?.files
    if (!selectedFiles?.length) return
    setUploading(true)
    setError(null)
    const url = selectedFiles.length === 1
      ? `${API_BASE}/knowledge/upload`
      : `${API_BASE}/knowledge/upload-bulk`
    try {
      if (selectedFiles.length === 1) {
        const form = new FormData()
        form.append('file', selectedFiles[0])
        console.log('[Knowledge Bank] Uploading to', url, 'filename:', selectedFiles[0].name)
        const res = await fetch(url, { method: 'POST', body: form })
        console.log('[Knowledge Bank] Response:', res.status, res.statusText, 'Content-Type:', res.headers.get('content-type'))
        if (!res.ok) {
          const text = await res.text()
          let errDetail = res.statusText
          try {
            const parsed = JSON.parse(text)
            errDetail = parsed.detail || errDetail
          } catch {
            if (text.includes('<!doctype') || text.includes('<html')) {
              errDetail = `Request got ${res.status} — not reaching API. Check Vite proxy (dashboard/vite.config.js) forwards /api to localhost:8000.`
              console.warn('[Knowledge Bank] Got HTML instead of JSON:', text.slice(0, 100) + '...')
            } else if (text.length < 200) {
              errDetail = text
            }
          }
          throw new Error(errDetail)
        }
      } else {
        const form = new FormData()
        for (let i = 0; i < selectedFiles.length; i++) form.append('files', selectedFiles[i])
        console.log('[Knowledge Bank] Bulk upload to', url, 'files:', selectedFiles.length)
        const res = await fetch(url, { method: 'POST', body: form })
        console.log('[Knowledge Bank] Response:', res.status, res.statusText, 'Content-Type:', res.headers.get('content-type'))
        if (!res.ok) {
          const text = await res.text()
          let errDetail = res.statusText
          try {
            const parsed = JSON.parse(text)
            errDetail = parsed.detail || errDetail
          } catch {
            if (text.includes('<!doctype') || text.includes('<html')) {
              errDetail = `Request got ${res.status} — not reaching API. Check Vite proxy (dashboard/vite.config.js) forwards /api to localhost:8000.`
              console.warn('[Knowledge Bank] Got HTML instead of JSON:', text.slice(0, 100) + '...')
            } else if (text.length < 200) {
              errDetail = text
            }
          }
          throw new Error(errDetail)
        }
        const data = await res.json()
        const failed = data.results?.filter(r => !r.success)
        if (failed?.length) setError(`${failed.length} file(s) failed: ${failed.map(f => f.error).join('; ')}`)
      }
      fetchFiles()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleUploadUrl = async () => {
    try {
      setUploading(true)
      setError(null)
      const form = new FormData()
      form.append('url', urlInput.trim())
      const res = await fetch(`${API_BASE}/knowledge/upload-url`, { method: 'POST', body: form })
      if (!res.ok) {
        const text = await res.text()
        let errDetail = res.statusText
        try {
          const parsed = JSON.parse(text)
          errDetail = parsed.detail || errDetail
        } catch {
          if (text.includes('<!doctype') || text.includes('<html')) {
            errDetail = `Request got ${res.status} — not reaching API. Check Vite proxy forwards /api to localhost:8000.`
          } else if (text.length < 200) errDetail = text
        }
        throw new Error(errDetail)
      }
      setUrlInput('')
      fetchFiles()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  const handleSaveTags = async (id) => {
    const tags = editingTags.split(',').map(t => t.trim()).filter(Boolean)
    try {
      const res = await fetch(`${API_BASE}/knowledge/files/${id}/tags`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags }),
      })
      if (!res.ok) throw new Error('Failed to update tags')
      setEditingTagsId(null)
      fetchFiles()
    } catch (err) {
      setError(err.message)
    }
  }

  const handleExpand = async (id) => {
    if (chunks[id]) {
      setExpandedId(expandedId === id ? null : id)
      return
    }
    try {
      const res = await fetch(`${API_BASE}/knowledge/files/${id}/chunks`)
      if (!res.ok) throw new Error('Failed to fetch chunks')
      const data = await res.json()
      setChunks(prev => ({ ...prev, [id]: data.chunks }))
      setExpandedId(id)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDownload = async (id, filename) => {
    try {
      const res = await fetch(`${API_BASE}/knowledge/files/${id}`)
      if (!res.ok) throw new Error('Failed to download')
      const data = await res.json()
      const blob = new Blob([data.content], { type: 'text/plain' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = filename || 'document.txt'
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this file from the Knowledge Bank?')) return
    try {
      const res = await fetch(`${API_BASE}/knowledge/files/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed to delete')
      fetchFiles()
      if (expandedId === id) setExpandedId(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const formatSize = (bytes) => {
    if (bytes == null || isNaN(bytes)) return '—'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">Knowledge Bank</h2>
          <p className="text-sm text-slate-400 mt-1">
            Upload documents (PDF, TXT, DOCX, PPTX, MD). The agent can search them when you ask questions.
          </p>
        </div>
        <div className="flex gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.docx,.pptx,.md"
            multiple
            onChange={handleUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={!configured || uploading}
            className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
          <button
            onClick={fetchFiles}
            className="text-sm text-emerald-400 hover:text-emerald-300 px-3 py-1.5 rounded-lg border border-emerald-500/30"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Search + URL upload */}
      {configured && (
        <div className="space-y-3">
          <input
            type="text"
            placeholder="Search by filename or tag..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg bg-slate-800/80 border border-slate-700 px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
          />
          <div className="flex gap-2">
            <input
              type="url"
              placeholder="https://example.com/article (HTML or plain text)"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleUploadUrl()}
              className="flex-1 rounded-lg bg-slate-800/80 border border-slate-700 px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
            />
            <button
              onClick={handleUploadUrl}
              disabled={!urlInput.trim() || uploading}
              className="px-4 py-2 rounded-lg bg-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-600 disabled:opacity-50"
            >
              Add from URL
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-lg px-4 py-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12 text-slate-400">Loading…</div>
      ) : !configured ? (
        <div className="bg-slate-800/30 rounded-xl border border-dashed border-slate-700 p-8 text-center text-slate-400">
          <p>Set KNOWLEDGE_DATABASE_URL and create the <code className="text-slate-300">rowan-data</code> database with pgvector.</p>
          <p className="text-sm mt-2">See .env.example for setup instructions.</p>
        </div>
      ) : files.length === 0 ? (
        <div className="bg-slate-800/30 rounded-xl border border-dashed border-slate-700 p-8 text-center text-slate-400">
          <p>{searchQuery ? 'No matching documents.' : 'No documents yet. Upload PDF, TXT, DOCX, PPTX, or MD files.'}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {files.map((f) => (
            <div
              key={f.id}
              className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-100 truncate">{f.filename}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {formatSize(f.size_bytes)} · {f.chunk_count} chunks · searched {f.search_count}×
                  </p>
                  {f.uploaded_at && (
                    <p className="text-xs text-slate-600 mt-0.5">{formatDate(f.uploaded_at)}</p>
                  )}
                  {(f.tags?.length > 0 || editingTagsId === f.id) && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {editingTagsId === f.id ? (
                        <>
                          <input
                            type="text"
                            value={editingTags}
                            onChange={(e) => setEditingTags(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Escape') setEditingTagsId(null)
                              if (e.key === 'Enter') handleSaveTags(f.id)
                            }}
                            placeholder="tag1, tag2"
                            className="flex-1 min-w-[120px] rounded bg-slate-900 px-2 py-1 text-sm text-slate-100"
                            autoFocus
                          />
                          <button onClick={() => handleSaveTags(f.id)} className="text-xs text-emerald-400">Save</button>
                          <button onClick={() => setEditingTagsId(null)} className="text-xs text-slate-400">Cancel</button>
                        </>
                      ) : (
                        <>
                          {(f.tags || []).map((t) => (
                            <span key={t} className="inline-flex items-center rounded bg-slate-700/80 px-2 py-0.5 text-xs text-slate-300">
                              {t}
                            </span>
                          ))}
                          <button onClick={() => { setEditingTagsId(f.id); setEditingTags((f.tags || []).join(', ')) }} className="text-xs text-slate-500 hover:text-slate-300">
                            Edit
                          </button>
                        </>
                      )}
                    </div>
                  )}
                  {(!f.tags?.length && editingTagsId !== f.id) && (
                    <button onClick={() => { setEditingTagsId(f.id); setEditingTags('') }} className="mt-2 text-xs text-slate-500 hover:text-slate-300">
                      + Add tags
                    </button>
                  )}
                </div>
                <div className="flex gap-2 ml-2">
                  <button
                    onClick={() => handleExpand(f.id)}
                    className="text-xs text-emerald-400 hover:text-emerald-300 px-2 py-1 rounded"
                  >
                    {expandedId === f.id ? 'Collapse' : 'Expand'}
                  </button>
                  <button
                    onClick={() => handleDownload(f.id, f.filename)}
                    className="text-xs text-slate-300 hover:text-slate-100 px-2 py-1 rounded"
                  >
                    Download
                  </button>
                  <button
                    onClick={() => handleDelete(f.id)}
                    className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded"
                  >
                    Delete
                  </button>
                </div>
              </div>
              {expandedId === f.id && chunks[f.id] && (
                <div className="mt-4 pt-4 border-t border-slate-700/50 space-y-3">
                  {chunks[f.id].map((c, i) => (
                    <div key={c.id} className="bg-slate-900/50 rounded-lg p-3 text-sm text-slate-300">
                      <span className="text-slate-500 text-xs">Chunk {c.chunk_index + 1}</span>
                      <pre className="mt-1 whitespace-pre-wrap font-sans">{c.content}</pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ==================== CORE MEMORY COMPONENTS ====================

// Core Memory Block Component
function CoreMemoryEditor({ blockType, content, readOnly, onSave, onChange, onReadOnlyChange }) {
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [localContent, setLocalContent] = useState(content)
  const [localReadOnly, setLocalReadOnly] = useState(readOnly)

  useEffect(() => {
    setLocalContent(content)
    setLocalReadOnly(readOnly)
  }, [content, readOnly])

  const handleSave = async () => {
    setIsSaving(true)
    setSaveError(null)
    
    try {
      const res = await fetch(`${API_BASE}/core-memory/${blockType}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: localContent }),
      })
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      
      onSave?.(localContent)
    } catch (err) {
      setSaveError(err.message || 'Failed to save')
    } finally {
      setIsSaving(false)
    }
  }

  const blockTitles = {
    system_instructions: 'System Instructions',
    user: 'User',
    identity: 'Identity',
    ideaspace: 'Ideaspace',
    principles: 'Principles',
  }

  const blockDescriptions = {
    system_instructions: 'Read-only system instructions for the agent.',
    user: 'Information about the user that the agent should remember.',
    identity: "The agent's identity, personality, and self-concept.",
    ideaspace: 'Working memory for ongoing thoughts and ideas.',
    principles: 'Operational heuristics learned through experience. Updated via weekly synthesis.',
  }

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h3 className="text-lg font-semibold text-slate-100">{blockTitles[blockType]}</h3>
          <p className="text-xs text-slate-400">{blockDescriptions[blockType]}</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={localReadOnly}
            onChange={(e) => {
              setLocalReadOnly(e.target.checked)
              onReadOnlyChange?.(e.target.checked)
            }}
            disabled={blockType === 'system_instructions'}
            className="rounded border-slate-600 bg-slate-700 text-emerald-500 focus:ring-emerald-500/50 disabled:opacity-50"
          />
          <span className={blockType === 'system_instructions' ? 'opacity-50' : ''}>Read-only</span>
        </label>
      </div>
      
      <textarea
        value={localContent}
        onChange={(e) => {
          setLocalContent(e.target.value)
          onChange?.(e.target.value)
        }}
        disabled={isSaving}
        className="w-full h-48 rounded-lg bg-slate-900/80 border border-slate-700 px-3 py-2 text-slate-100 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50 disabled:opacity-50 disabled:cursor-not-allowed"
        placeholder={`Enter ${blockTitles[blockType].toLowerCase()} content...`}
      />
      
      <div className="flex items-center justify-between mt-3">
        <div>
          {saveError && (
            <span className="text-sm text-red-400">{saveError}</span>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={isSaving || localContent === content}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isSaving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  )
}

// Core Memory Tab Component
function CoreMemoryTab() {
  const [blocks, setBlocks] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // Read-only states control AI editing protection, not user editing
  // System instructions is protected from AI by default (readOnly=true for AI)
  const [readOnlyStates, setReadOnlyStates] = useState({
    system_instructions: true,  // AI cannot edit system instructions
    user: false,
    identity: false,
    ideaspace: false,
    principles: false,
  })

  const fetchBlocks = async () => {
    try {
      const res = await fetch(`${API_BASE}/core-memory`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setBlocks(data.blocks || {})
    } catch (err) {
      setError(err.message || 'Failed to load core memory')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchBlocks()
  }, [])

  const handleBlockSave = (blockType) => (content) => {
    setBlocks((prev) => ({
      ...prev,
      [blockType]: { ...prev[blockType], content },
    }))
  }

  const handleReadOnlyChange = (blockType) => (readOnly) => {
    setReadOnlyStates((prev) => ({
      ...prev,
      [blockType]: readOnly,
    }))
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-slate-400">Loading core memory...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-red-400 mb-2">{error}</p>
          <button
            onClick={fetchBlocks}
            className="text-emerald-400 hover:text-emerald-300 text-sm"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const blockOrder = ['system_instructions', 'user', 'identity', 'ideaspace', 'principles']

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">Core Memory</h2>
          <p className="text-sm text-slate-400 mt-1">
            Edit the agent's core memory blocks. Changes are saved to the database and take effect immediately.
          </p>
        </div>
        <button
          onClick={fetchBlocks}
          className="text-sm text-emerald-400 hover:text-emerald-300 px-3 py-1.5 rounded-lg border border-emerald-500/30 hover:border-emerald-500/50 transition-colors"
        >
          Refresh
        </button>
      </div>
      
      <div className="space-y-6">
        {blockOrder.map((blockType) => (
          <CoreMemoryEditor
            key={blockType}
            blockType={blockType}
            content={blocks[blockType]?.content || ''}
            readOnly={readOnlyStates[blockType]}
            onSave={handleBlockSave(blockType)}
            onReadOnlyChange={handleReadOnlyChange(blockType)}
          />
        ))}
      </div>
    </div>
  )
}

// ==================== CHAT COMPONENTS ====================

// Chat Tab Component
const ACCEPTED_FILE_TYPES = '.png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.pptx,.docx,.md'

function ChatTab() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState([])
  const [loading, setLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const messagesEndRef = useRef(null)
  const messagesContainerRef = useRef(null)
  const loadingRef = useRef(false)
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)
  const emojiPickerRef = useRef(null)
  const userJustSentRef = useRef(false)
  const wasNearBottomRef = useRef(true)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const isNearBottom = (el, threshold = 120) => {
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold
  }

  useEffect(() => {
    // Only auto-scroll when: user just sent a message (waiting for reply), or they were already at bottom
    if (userJustSentRef.current || loadingRef.current || wasNearBottomRef.current) {
      scrollToBottom()
    }
    userJustSentRef.current = false
  }, [messages])

  // Reset textarea height when input is cleared
  useEffect(() => {
    if (!input && inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
  }, [input])

  // Close emoji picker when clicking outside
  useEffect(() => {
    if (!showEmojiPicker) return
    const handleOutsideClick = (e) => {
      if (emojiPickerRef.current && !emojiPickerRef.current.contains(e.target)) {
        setShowEmojiPicker(false)
      }
    }
    // setTimeout(0) skips the current click event that opened the picker
    const timer = setTimeout(() => document.addEventListener('click', handleOutsideClick), 0)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('click', handleOutsideClick)
    }
  }, [showEmojiPicker])

  // Load conversation history from the DB
  const loadHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/messages?thread_id=main&limit=200`)
      if (!res.ok) return
      const data = await res.json()
      setMessages(data.messages || [])
    } catch {
      // silently ignore polling errors
    } finally {
      setHistoryLoaded(true)
    }
  }

  // Load on mount + poll every 10s for cron messages and other updates
  useEffect(() => {
    loadHistory()
    const interval = setInterval(() => {
      if (!loadingRef.current) loadHistory()
    }, 10000)
    return () => clearInterval(interval)
  }, [])

  const sendMessage = async () => {
    const text = input.trim()
    const hasFiles = attachments.length > 0
    if ((!text && !hasFiles) || loading) return

    const displayText = text || (hasFiles ? `[${attachments.length} file(s) attached]` : '')

    // Build preview data for images before clearing attachments
    const attachmentPreviews = await Promise.all(
      attachments.map((f) => {
        const isImage = f.type.startsWith('image/')
        if (!isImage) return Promise.resolve({ name: f.name, type: f.type, isImage: false })
        return new Promise((resolve) => {
          const reader = new FileReader()
          reader.onload = (e) => resolve({ name: f.name, type: f.type, isImage: true, dataUrl: e.target.result })
          reader.onerror = () => resolve({ name: f.name, type: f.type, isImage: false })
          reader.readAsDataURL(f)
        })
      })
    )

    setInput('')
    setAttachments([])
    setError(null)
    loadingRef.current = true
    setLoading(true)
    userJustSentRef.current = true
    setMessages((prev) => [...prev, {
      role: 'user',
      content: displayText,
      metadata: { role_display: 'User', attachments: attachmentPreviews },
    }])

    try {
      let res
      if (hasFiles) {
        const form = new FormData()
        form.append('message', text)
        form.append('thread_id', 'main')
        attachments.forEach((f) => form.append('files', f))
        res = await fetch(`${API_BASE}/chat/upload`, {
          method: 'POST',
          body: form,
        })
      } else {
        res = await fetch(`${API_BASE}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, thread_id: 'main' }),
        })
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      // Append assistant response from API — avoids full reload that can make chat "vanish"
      const data = await res.json()
      if (data?.response) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: data.response, metadata: {} },
        ])
      } else {
        await loadHistory()
      }
    } catch (err) {
      setError(err.message || 'Failed to send message')
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: null,
          metadata: {},
          error: err.message || 'Something went wrong.',
        },
      ])
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || [])
    const valid = files.filter((f) => {
      const ext = '.' + (f.name || '').split('.').pop().toLowerCase()
      return ACCEPTED_FILE_TYPES.split(',').includes(ext)
    })
    setAttachments((prev) => [...prev, ...valid])
    e.target.value = ''
  }

  const removeAttachment = (idx) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx))
  }

  const visibleMessages = messages.filter((m) => m.role !== 'tool' && m.metadata?.role_display !== 'heartbeat')

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0">
      {/* Messages */}
      <main
        ref={messagesContainerRef}
        className="flex-1 overflow-y-auto overflow-x-hidden px-6 py-6"
        onScroll={() => {
          const el = messagesContainerRef.current
          wasNearBottomRef.current = el ? isNearBottom(el) : true
        }}
      >
        <div className="max-w-2xl mx-auto space-y-6 overflow-x-hidden min-w-0">
          {!historyLoaded ? (
            <div className="flex items-center justify-center h-32">
              <span className="text-slate-400">Loading conversation...</span>
            </div>
          ) : visibleMessages.length === 0 ? (
            <div className="text-center py-16 text-slate-500">
              <p className="text-lg">Start a conversation</p>
              <p className="text-sm mt-2">Send a message to get started.</p>
            </div>
          ) : null}

          {visibleMessages.map((msg, i) => {
            const isCron = msg.metadata?.role_display === 'cron'

            if (isCron) {
              return (
                <div key={i} className="flex justify-start">
                  <div className="max-w-[85%]">
                    <p className="text-xs text-indigo-400 mb-1">⏰ Automated Cron</p>
                    <div className="bg-indigo-900/20 text-indigo-200 border border-indigo-700/50 rounded-2xl px-4 py-3">
                      <p className="whitespace-pre-wrap break-words text-sm">{msg.content}</p>
                    </div>
                  </div>
                </div>
              )
            }

            return (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                    msg.role === 'user'
                      ? 'bg-emerald-600/80 text-white'
                      : msg.error
                        ? 'bg-red-900/40 text-red-200 border border-red-800/50'
                        : 'bg-slate-800 text-slate-100 border border-slate-700/50'
                  }`}
                >
                  {msg.role === 'assistant' ? (
                    <div className="[&_strong]:font-semibold [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5 [&_p]:my-1 first:[&_p]:mt-0 last:[&_p]:mb-0">
                      <ReactMarkdown
                        components={{
                          p: ({ children }) => <p className="whitespace-pre-wrap break-words">{children}</p>,
                        }}
                      >
                        {cleanAssistantContent(msg.content) ?? msg.error ?? ''}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <div>
                      {msg.metadata?.attachments?.length > 0 && (
                        <div className="flex flex-wrap gap-2 mb-2">
                          {msg.metadata.attachments.map((att, ai) =>
                            att.isImage && att.dataUrl ? (
                              <img
                                key={ai}
                                src={att.dataUrl}
                                alt={att.name}
                                title={att.name}
                                className="h-20 w-20 rounded-lg object-cover border border-white/20 cursor-pointer hover:opacity-90"
                                onClick={() => window.open(att.dataUrl, '_blank')}
                              />
                            ) : (
                              <div
                                key={ai}
                                className="flex items-center gap-1.5 rounded-lg bg-white/10 px-2 py-1.5 text-xs text-white/80"
                                title={att.name}
                              >
                                <span>📎</span>
                                <span className="max-w-[120px] truncate">{att.name}</span>
                              </div>
                            )
                          )}
                        </div>
                      )}
                      {msg.content && msg.content !== `[${msg.metadata?.attachments?.length} file(s) attached]` && (
                        <p className="whitespace-pre-wrap break-words">{msg.content ?? msg.error}</p>
                      )}
                      {!msg.content && !msg.metadata?.attachments?.length && (
                        <p className="whitespace-pre-wrap break-words">{msg.error}</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )
          })}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-800 border border-slate-700/50 rounded-2xl px-4 py-3">
                <span className="inline-flex gap-1">
                  <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                  <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                  <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" />
                </span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Input */}
      <footer className="border-t border-slate-800 px-6 py-4">
        <div className="max-w-2xl mx-auto flex flex-col gap-2">
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {attachments.map((f, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 rounded-lg bg-slate-700/80 px-2 py-1 text-sm text-slate-200"
                >
                  {f.name}
                  <button
                    type="button"
                    onClick={() => removeAttachment(i)}
                    className="text-slate-400 hover:text-red-400"
                    aria-label="Remove"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-3 items-end">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_FILE_TYPES}
              multiple
              onChange={handleFileSelect}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
              className="shrink-0 rounded-xl bg-slate-800 border border-slate-700 px-3 py-3 text-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
              title="Add files (images, PDF, DOCX, etc.)"
            >
              +
            </button>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                const ta = e.target
                ta.style.height = 'auto'
                ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
              }}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              disabled={loading}
              rows={1}
              className="flex-1 min-h-[44px] max-h-[200px] rounded-xl bg-slate-800/80 border border-slate-700 px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50 disabled:opacity-50 overflow-y-auto"
              style={{ resize: 'none' }}
            />
            {/* Emoji picker */}
          <div className="relative" ref={emojiPickerRef}>
            <button
              type="button"
              onClick={() => setShowEmojiPicker((v) => !v)}
              disabled={loading}
              className="rounded-xl bg-slate-800 border border-slate-700 px-3 py-3 text-xl hover:bg-slate-700 disabled:opacity-50 transition-colors"
              title="Insert emoji"
            >
              😊
            </button>
            {showEmojiPicker && (
              <div className="absolute bottom-full right-0 mb-2 z-50">
                <Picker
                  data={emojiData}
                  theme="dark"
                  onEmojiSelect={(emoji) => {
                    setInput((prev) => prev + emoji.native)
                    setShowEmojiPicker(false)
                    inputRef.current?.focus()
                  }}
                />
              </div>
            )}
          </div>
            <button
              onClick={sendMessage}
              disabled={loading || (!input.trim() && attachments.length === 0)}
              className="shrink-0 rounded-xl bg-emerald-600 px-5 py-3 font-medium text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Send
            </button>
          </div>
        </div>
        {error && (
          <p className="max-w-2xl mx-auto mt-2 text-sm text-red-400">{error}</p>
        )}
      </footer>
    </div>
  )
}

// ==================== HEARTBEAT TAB ====================

// ==================== TOOLS TAB ====================

function ToolsTab() {
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API_BASE}/tools`)
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText)
        return res.json()
      })
      .then((data) => setCategories(data.categories || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-slate-400">Loading tools...</span>
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-6">
        <p className="text-red-400">Failed to load tools: {error}</p>
      </div>
    )
  }

  const dashboardAiCategory = {
    category: 'Dashboard AI (Notes tab)',
    tools: [
      { name: 'Summarize board', description: 'In Notes: AI tab → Summarize board. Sends board content to the agent for a 2–4 paragraph summary.' },
      { name: 'Organize', description: 'In Notes: AI tab → Organize. AI suggests grouping or layout for notes based on content.' },
      { name: 'Recall (Hindsight)', description: 'In Notes: AI tab → Recall. Semantic search over lived experience. Enter a query to pull relevant memories.' },
    ],
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-slate-100">the agent&apos;s Tools</h2>
        <p className="text-sm text-slate-400 mt-1">
          All tools the agent can use, grouped by category. Ask the agent to use any of these by name or by describing what you need.
        </p>
      </div>
      <div className="space-y-6">
        {categories.map((cat) => (
          <div
            key={cat.category}
            className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden"
          >
            <div className="px-4 py-3 bg-slate-800/80 border-b border-slate-700/50">
              <h3 className="font-medium text-emerald-400">{cat.category}</h3>
            </div>
            <ul className="divide-y divide-slate-700/50">
              {cat.tools.map((t) => (
                <li key={t.name} className="px-4 py-3 flex gap-4 items-start">
                  <code className="text-sm font-mono text-slate-200 bg-slate-900/80 px-2 py-1 rounded shrink-0">
                    {t.name}
                  </code>
                  <p className="text-sm text-slate-400 flex-1">{t.description}</p>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/80 border-b border-slate-700/50">
            <h3 className="font-medium text-emerald-400">{dashboardAiCategory.category}</h3>
          </div>
          <ul className="divide-y divide-slate-700/50">
            {dashboardAiCategory.tools.map((t) => (
              <li key={t.name} className="px-4 py-3 flex gap-4 items-start">
                <code className="text-sm font-mono text-slate-200 bg-slate-900/80 px-2 py-1 rounded shrink-0">
                  {t.name}
                </code>
                <p className="text-sm text-slate-400 flex-1">{t.description}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

// ==================== HEARTBEAT TAB ====================

// ── Heartbeat Tab ──────────────────────────────────────────────────────────────

const HOUR_LABELS = Array.from({ length: 24 }, (_, i) => {
  const h = i % 12 || 12
  const ampm = i < 12 ? 'AM' : 'PM'
  return `${h} ${ampm}`
})

function HourSelect({ value, onChange, label }) {
  return (
    <div>
      <p className="text-slate-400 text-xs mb-1">{label}</p>
      <select
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="bg-slate-800 border border-slate-600 text-slate-100 text-sm rounded-lg px-3 py-1.5 w-full focus:outline-none focus:border-indigo-500"
      >
        {HOUR_LABELS.map((lbl, i) => (
          <option key={i} value={i}>{lbl}</option>
        ))}
      </select>
    </div>
  )
}

function NumInput({ value, onChange, label, min = 1, max = 480 }) {
  return (
    <div>
      <p className="text-slate-400 text-xs mb-1">{label}</p>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={e => onChange(Math.max(min, Math.min(max, Number(e.target.value))))}
          className="bg-slate-800 border border-slate-600 text-slate-100 text-sm rounded-lg px-3 py-1.5 w-24 focus:outline-none focus:border-indigo-500"
        />
        <span className="text-slate-500 text-xs">min</span>
      </div>
    </div>
  )
}

function ScheduleVisualizer({ cfg }) {
  // 24-cell bar, one cell per hour
  const cells = Array.from({ length: 24 }, (_, h) => {
    const ws = cfg.wonder_start, we = cfg.wonder_end
    const wks = cfg.work_start, wke = cfg.work_end
    const inNight = ws > we ? (h >= ws || h < we) : (h >= ws && h < we)
    const inWork  = wks <= wke ? (h >= wks && h < wke) : (h >= wks || h < wke)
    if (!inNight) return { mode: 'day',    color: 'bg-slate-700' }
    if (inWork)   return { mode: 'work',   color: 'bg-amber-500' }
    return              { mode: 'wonder', color: 'bg-indigo-500' }
  })
  return (
    <div>
      <p className="text-slate-400 text-xs mb-2">24-hour schedule preview</p>
      <div className="flex gap-0.5">
        {cells.map((c, h) => (
          <div key={h} className="flex-1 flex flex-col items-center gap-0.5">
            <div className={`h-5 w-full rounded-sm ${c.color}`} title={`${HOUR_LABELS[h]}: ${c.mode}`} />
          </div>
        ))}
      </div>
      <div className="flex gap-0.5 mt-0.5">
        {[0,6,12,18,23].map(h => (
          <div key={h} className="text-slate-600 text-xs" style={{ marginLeft: h === 0 ? 0 : `${(h/24)*100}%`, position: h === 0 ? 'static' : 'absolute' }}>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-4 mt-2 text-xs text-slate-400">
        <span><span className="inline-block w-2.5 h-2.5 rounded-sm bg-indigo-500 mr-1" />Wonder</span>
        <span><span className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-500 mr-1" />Work</span>
        <span><span className="inline-block w-2.5 h-2.5 rounded-sm bg-slate-700 mr-1" />Day</span>
      </div>
    </div>
  )
}

function HeartbeatTab() {
  const [status, setStatus] = useState(null)
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedPrompts, setExpandedPrompts] = useState({})

  // Config state
  const [cfg, setCfg] = useState(null)
  const [cfgDirty, setCfgDirty] = useState(false)
  const [cfgSaving, setCfgSaving] = useState(false)
  const [cfgMsg, setCfgMsg] = useState(null)

  // Prompt editor state
  const [prompts, setPrompts] = useState(null)          // { wonder: {text, is_custom}, work: {text, is_custom} }
  const [promptEdits, setPromptEdits] = useState({})    // { wonder: string, work: string } — live edits
  const [promptDirty, setPromptDirty] = useState({})    // { wonder: bool, work: bool }
  const [promptSaving, setPromptSaving] = useState({})  // { wonder: bool, work: bool }
  const [promptMsg, setPromptMsg] = useState({})        // { wonder: {ok,text}, work: {ok,text} }

  // Restart state
  const [restarting, setRestarting] = useState(false)
  const [restartCountdown, setRestartCountdown] = useState(0)
  const [restartMsg, setRestartMsg] = useState(null)

  // Start scheduler state
  const [startingScheduler, setStartingScheduler] = useState(false)
  const [startSchedulerMsg, setStartSchedulerMsg] = useState(null)

  const load = async () => {
    try {
      const [sRes, hRes, cRes, pRes] = await Promise.all([
        fetch(`${API_BASE}/heartbeat/status`),
        fetch(`${API_BASE}/heartbeat/sessions?limit=50`),
        fetch(`${API_BASE}/heartbeat/config`),
        fetch(`${API_BASE}/heartbeat/prompts`),
      ])
      if (sRes.ok) setStatus(await sRes.json())
      if (hRes.ok) { const d = await hRes.json(); setSessions(d.sessions || []) }
      if (cRes.ok) { const c = await cRes.json(); setCfg(c); setCfgDirty(false) }
      if (pRes.ok) {
        const p = await pRes.json()
        setPrompts(p)
        setPromptEdits({ wonder: p.wonder.text, work: p.work.text })
        setPromptDirty({ wonder: false, work: false })
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  const togglePrompt = (i) => setExpandedPrompts(p => ({ ...p, [i]: !p[i] }))

  const updateCfg = (key, val) => {
    setCfg(prev => ({ ...prev, [key]: val }))
    setCfgDirty(true)
    setCfgMsg(null)
  }

  const saveCfg = async () => {
    setCfgSaving(true)
    setCfgMsg(null)
    try {
      const res = await fetch(`${API_BASE}/heartbeat/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      })
      if (res.ok) {
        const d = await res.json()
        setCfg(d.config)
        setCfgDirty(false)
        setCfgMsg({ ok: true, text: 'Saved. Scheduler will pick up changes on next tick.' })
      } else {
        setCfgMsg({ ok: false, text: 'Save failed.' })
      }
    } catch (e) {
      setCfgMsg({ ok: false, text: `Error: ${e.message}` })
    } finally {
      setCfgSaving(false)
    }
  }

  const updatePromptEdit = (mode, val) => {
    setPromptEdits(p => ({ ...p, [mode]: val }))
    setPromptDirty(d => ({ ...d, [mode]: true }))
    setPromptMsg(m => ({ ...m, [mode]: null }))
  }

  const savePrompt = async (mode) => {
    setPromptSaving(s => ({ ...s, [mode]: true }))
    setPromptMsg(m => ({ ...m, [mode]: null }))
    try {
      const body = {
        wonder_prompt: mode === 'wonder' ? promptEdits.wonder : (prompts?.wonder.is_custom ? promptEdits.wonder : null),
        work_prompt:   mode === 'work'   ? promptEdits.work   : (prompts?.work.is_custom   ? promptEdits.work   : null),
      }
      // Only send the one being saved
      if (mode === 'wonder') body.work_prompt = prompts?.work.is_custom ? promptEdits.work : null
      if (mode === 'work')   body.wonder_prompt = prompts?.wonder.is_custom ? promptEdits.wonder : null

      const res = await fetch(`${API_BASE}/heartbeat/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        const d = await res.json()
        setPrompts(d)
        setPromptEdits(e => ({ ...e, [mode]: d[mode].text }))
        setPromptDirty(dirty => ({ ...dirty, [mode]: false }))
        setPromptMsg(m => ({ ...m, [mode]: { ok: true, text: d[mode].is_custom ? 'Custom prompt saved.' : 'Reverted to built-in default.' } }))
      } else {
        setPromptMsg(m => ({ ...m, [mode]: { ok: false, text: 'Save failed.' } }))
      }
    } catch (e) {
      setPromptMsg(m => ({ ...m, [mode]: { ok: false, text: `Error: ${e.message}` } }))
    } finally {
      setPromptSaving(s => ({ ...s, [mode]: false }))
    }
  }

  const revertPrompt = async (mode) => {
    if (!window.confirm(`Revert ${mode} prompt to built-in default?`)) return
    setPromptSaving(s => ({ ...s, [mode]: true }))
    try {
      const body = {
        wonder_prompt: mode === 'wonder' ? null : (prompts?.wonder.is_custom ? promptEdits.wonder : null),
        work_prompt:   mode === 'work'   ? null : (prompts?.work.is_custom   ? promptEdits.work   : null),
      }
      const res = await fetch(`${API_BASE}/heartbeat/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        const d = await res.json()
        setPrompts(d)
        setPromptEdits(e => ({ ...e, [mode]: d[mode].text }))
        setPromptDirty(dirty => ({ ...dirty, [mode]: false }))
        setPromptMsg(m => ({ ...m, [mode]: { ok: true, text: 'Reverted to built-in default.' } }))
      }
    } finally {
      setPromptSaving(s => ({ ...s, [mode]: false }))
    }
  }

  const triggerRestart = async () => {
    if (!window.confirm('This will rebuild the dashboard and restart the server (~20s downtime). Continue?')) return
    setRestarting(true)
    setRestartMsg(null)
    setRestartCountdown(8)

    // Countdown timer
    const tick = setInterval(() => {
      setRestartCountdown(n => {
        if (n <= 1) { clearInterval(tick); return 0 }
        return n - 1
      })
    }, 1000)

    try {
      const res = await fetch(`${API_BASE}/heartbeat/restart`, { method: 'POST' })
      if (res.ok) {
        const d = await res.json()
        setRestartMsg({ ok: true, text: d.message })
        // After countdown, try to reload
        setTimeout(() => {
          setRestarting(false)
          window.location.reload()
        }, 9000)
      } else {
        setRestartMsg({ ok: false, text: 'Restart request failed.' })
        setRestarting(false)
        clearInterval(tick)
      }
    } catch (e) {
      // Expected — server is restarting, connection dropped
      setRestartMsg({ ok: true, text: 'API restarting… page will reload shortly.' })
      setTimeout(() => {
        setRestarting(false)
        window.location.reload()
      }, 9000)
    }
  }

  const timeAgo = (iso) => {
    if (!iso) return null
    const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
    if (m < 1) return 'just now'
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  }

  const timeUntil = (iso) => {
    if (!iso) return '—'
    const m = Math.ceil((new Date(iso).getTime() - Date.now()) / 60000)
    if (m <= 0) return 'overdue'
    if (m < 60) return `in ~${m}m`
    return `in ~${Math.floor(m / 60)}h ${m % 60}m`
  }

  const isOk = (r) => r && r.trim() === 'HEARTBEAT_OK'

  const dotColor = !status?.last_run ? 'bg-slate-600'
    : (Date.now() - new Date(status.last_run).getTime()) < (status.interval_minutes * 2 * 60000)
    ? 'bg-emerald-400' : 'bg-yellow-400'

  if (loading) return <div className="p-6 text-slate-400 text-sm">Loading...</div>

  return (
    <div className="space-y-6 max-w-3xl">

      {/* ── Schedule Config ── */}
      {cfg && (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 space-y-5">
          <h2 className="font-semibold text-slate-100">Schedule</h2>

          {/* Visualizer */}
          <ScheduleVisualizer cfg={cfg} />

          {/* Wonder window */}
          <div>
            <p className="text-xs font-medium text-indigo-400 uppercase tracking-wider mb-3">Wonder Window (overnight exploration)</p>
            <div className="grid grid-cols-2 gap-4">
              <HourSelect label="Start" value={cfg.wonder_start} onChange={v => updateCfg('wonder_start', v)} />
              <HourSelect label="End"   value={cfg.wonder_end}   onChange={v => updateCfg('wonder_end', v)} />
            </div>
          </div>

          {/* Work window */}
          <div>
            <p className="text-xs font-medium text-amber-400 uppercase tracking-wider mb-3">Work Window (pre-online prep — inside night window)</p>
            <div className="grid grid-cols-2 gap-4">
              <HourSelect label="Start" value={cfg.work_start} onChange={v => updateCfg('work_start', v)} />
              <HourSelect label="End"   value={cfg.work_end}   onChange={v => updateCfg('work_end', v)} />
            </div>
          </div>

          {/* Intervals */}
          <div>
            <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-3">Intervals</p>
            <div className="grid grid-cols-2 gap-4">
              <NumInput label="Night interval (Wonder/Work)" value={cfg.night_interval} onChange={v => updateCfg('night_interval', v)} />
              <NumInput label="Day interval"                 value={cfg.day_interval}   onChange={v => updateCfg('day_interval', v)} />
            </div>
          </div>

          {/* Save */}
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={saveCfg}
              disabled={!cfgDirty || cfgSaving}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {cfgSaving ? 'Saving…' : 'Save Schedule'}
            </button>
            {cfgMsg && (
              <span className={`text-xs ${cfgMsg.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                {cfgMsg.text}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Prompt Editor ── */}
      {prompts && (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 space-y-6">
          <h2 className="font-semibold text-slate-100">Heartbeat Prompts</h2>
          <p className="text-slate-400 text-xs -mt-3">
            Edit the instructions the agent receives at the start of each heartbeat cycle.
            Changes take effect on the next heartbeat — no restart needed.
          </p>

          {[
            { mode: 'wonder', label: 'Wonder', color: 'text-indigo-400', border: 'border-indigo-800', badge: 'bg-indigo-900 text-indigo-300' },
            { mode: 'work',   label: 'Work',   color: 'text-amber-400',  border: 'border-amber-800',  badge: 'bg-amber-900  text-amber-300'  },
          ].map(({ mode, label, color, border, badge }) => (
            <div key={mode} className={`border ${border} rounded-lg p-4 space-y-3`}>
              <div className="flex items-center gap-2">
                <span className={`text-xs font-semibold uppercase tracking-wider ${color}`}>{label} Prompt</span>
                {prompts[mode]?.is_custom
                  ? <span className={`text-xs px-2 py-0.5 rounded-full ${badge}`}>custom</span>
                  : <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">built-in default</span>
                }
              </div>

              <textarea
                value={promptEdits[mode] ?? ''}
                onChange={e => updatePromptEdit(mode, e.target.value)}
                rows={12}
                className="w-full bg-slate-950 border border-slate-700 text-slate-200 text-xs font-mono rounded-lg px-3 py-2.5 resize-y focus:outline-none focus:border-indigo-500 leading-relaxed"
                placeholder={`Enter custom ${label} prompt…`}
              />

              <div className="flex items-center gap-3">
                <button
                  onClick={() => savePrompt(mode)}
                  disabled={!promptDirty[mode] || promptSaving[mode]}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {promptSaving[mode] ? 'Saving…' : 'Save'}
                </button>
                {prompts[mode]?.is_custom && (
                  <button
                    onClick={() => revertPrompt(mode)}
                    disabled={promptSaving[mode]}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 disabled:opacity-40 transition-colors"
                  >
                    Revert to default
                  </button>
                )}
                {promptMsg[mode] && (
                  <span className={`text-xs ${promptMsg[mode].ok ? 'text-emerald-400' : 'text-red-400'}`}>
                    {promptMsg[mode].text}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Status card ── */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotColor}`} />
          <h2 className="font-semibold text-slate-100">Status</h2>
        </div>
        <div className="grid grid-cols-2 gap-x-10 gap-y-3 text-sm">
          <div>
            <p className="text-slate-400 text-xs mb-0.5">Last run</p>
            <p className="text-slate-100">
              {status?.last_run
                ? `${timeAgo(status.last_run)} · ${new Date(status.last_run).toLocaleTimeString()}`
                : 'Never'}
            </p>
          </div>
          <div>
            <p className="text-slate-400 text-xs mb-0.5">Next expected</p>
            <p className="text-slate-100">{status?.last_run ? timeUntil(status.next_expected) : '—'}</p>
          </div>
          <div>
            <p className="text-slate-400 text-xs mb-0.5">Interval</p>
            <p className="text-slate-100">every {status?.interval_minutes ?? '?'} min</p>
          </div>
          <div>
            <p className="text-slate-400 text-xs mb-0.5">Total runs</p>
            <p className="text-slate-100">{status?.total_runs ?? 0}</p>
          </div>
        </div>
      </div>

      {/* ── Start Scheduler ── */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-5">
        <h2 className="font-semibold text-slate-100 mb-1">Start Scheduler</h2>
        <p className="text-slate-400 text-xs mb-4">
          The Hbeat tab configures schedule and prompts. Click below to start the heartbeat scheduler so heartbeats actually run. Logs: logs/services/heartbeat.log
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={async () => {
              setStartingScheduler(true)
              setStartSchedulerMsg(null)
              try {
                const res = await fetch(`${API_BASE}/heartbeat/start`, { method: 'POST' })
                const d = await res.json().catch(() => ({}))
                if (res.ok) {
                  setStartSchedulerMsg({ ok: true, text: d.message || 'Scheduler started.' })
                  load()
                } else {
                  setStartSchedulerMsg({ ok: false, text: d.detail || 'Failed to start.' })
                }
              } catch (e) {
                setStartSchedulerMsg({ ok: false, text: e.message || 'Failed to start.' })
              } finally {
                setStartingScheduler(false)
              }
            }}
            disabled={startingScheduler}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white px-4 py-2 rounded-lg text-sm font-medium"
          >
            {startingScheduler ? 'Starting…' : 'Start Scheduler'}
          </button>
          {startSchedulerMsg && (
            <span className={`text-sm ${startSchedulerMsg.ok ? 'text-emerald-400' : 'text-red-400'}`}>
              {startSchedulerMsg.text}
            </span>
          )}
        </div>
      </div>

      {/* ── Restart ── */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-5">
        <h2 className="font-semibold text-slate-100 mb-1">Restart Server</h2>
        <p className="text-slate-400 text-xs mb-4">
          Restarts the API server (port 8000). Use after changing .env or code.
          Expect ~5s downtime — the page will reload automatically. Vite dev server is not affected.
        </p>
        <div className="flex items-center gap-3">
          <button
            onClick={triggerRestart}
            disabled={restarting}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-rose-700 hover:bg-rose-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {restarting
              ? restartCountdown > 0 ? `Restarting… ${restartCountdown}s` : 'Reloading…'
              : '⟳ Restart the agent'}
          </button>
          {restartMsg && (
            <span className={`text-xs ${restartMsg.ok ? 'text-emerald-400' : 'text-red-400'}`}>
              {restartMsg.text}
            </span>
          )}
        </div>
      </div>

      {/* ── Session Ledger ── */}
      <div>
        <h2 className="font-semibold text-slate-300 mb-3 text-sm uppercase tracking-wider">Session Ledger</h2>
        {sessions.length === 0 ? (
          <div className="text-slate-500 text-sm bg-slate-900 border border-slate-700 rounded-xl p-5">
            <p className="mb-3">No heartbeats recorded yet. The Hbeat tab configures schedule and prompts — you must start the scheduler for heartbeats to run.</p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={async () => {
                  setStartingScheduler(true)
                  setStartSchedulerMsg(null)
                  try {
                    const res = await fetch(`${API_BASE}/heartbeat/start`, { method: 'POST' })
                    const d = await res.json().catch(() => ({}))
                    if (res.ok) {
                      setStartSchedulerMsg({ ok: true, text: d.message || 'Scheduler started.' })
                      load()
                    } else {
                      setStartSchedulerMsg({ ok: false, text: d.detail || 'Failed to start.' })
                    }
                  } catch (e) {
                    setStartSchedulerMsg({ ok: false, text: e.message || 'Failed to start.' })
                  } finally {
                    setStartingScheduler(false)
                  }
                }}
                disabled={startingScheduler}
                className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white px-4 py-2 rounded-lg text-sm font-medium"
              >
                {startingScheduler ? 'Starting…' : 'Start Scheduler'}
              </button>
              {startSchedulerMsg && (
                <span className={`text-sm ${startSchedulerMsg.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                  {startSchedulerMsg.text}
                </span>
              )}
            </div>
            <p className="mt-3 text-xs text-slate-600">Or run manually: <code className="text-slate-400">python -m scripts.run_heartbeat_scheduler</code></p>
          </div>
        ) : (
          <div className="space-y-2">
            {sessions.map((s, i) => (
              <div
                key={i}
                className={`border rounded-xl p-4 ${isOk(s.response) ? 'border-slate-800 bg-slate-900/40' : 'border-slate-700 bg-slate-900'}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-400">
                    {new Date(s.timestamp).toLocaleString()} · {timeAgo(s.timestamp)}
                  </span>
                  {isOk(s.response) && (
                    <span className="text-xs bg-slate-800 text-slate-500 px-2 py-0.5 rounded-full">Nothing to report</span>
                  )}
                </div>
                {s.response ? (
                  <p className={`text-sm whitespace-pre-wrap break-words leading-relaxed ${isOk(s.response) ? 'text-slate-500' : 'text-slate-200'}`}>
                    {s.response}
                  </p>
                ) : (
                  <p className="text-sm text-slate-500 italic">No response recorded</p>
                )}
                <button
                  onClick={() => togglePrompt(i)}
                  className="mt-2 text-xs text-slate-600 hover:text-slate-400 transition-colors"
                >
                  {expandedPrompts[i] ? '▲ hide prompt' : '▾ show prompt'}
                </button>
                {expandedPrompts[i] && (
                  <pre className="mt-2 text-xs text-slate-400 bg-slate-950 rounded-lg p-3 whitespace-pre-wrap break-words border border-slate-800">
                    {s.prompt}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== MAIN APP ====================

const TABS = [
  { id: 'chat', label: 'Chat' },
  { id: 'journal', label: 'Journal' },
  { id: 'notes', label: 'Notes' },
  { id: 'core', label: 'Core' },
  { id: 'cron', label: 'Cron' },
  { id: 'data', label: 'Data' },
  { id: 'heartbeat', label: 'Hbeat' },
  { id: 'tools', label: 'Tools' },
]

// Main App Component
function App() {
  const [activeTab, setActiveTab] = useState('chat')
  const [overlayLaunching, setOverlayLaunching] = useState(false)

  return (
    <div className="h-screen bg-slate-950 text-slate-100 flex flex-col overflow-hidden">
      {/* Header — title + Game Overlay button */}
      <header className="border-b border-slate-800 flex-shrink-0">
        <div className="px-5 py-3 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-100">Agent</h1>
          <button
            type="button"
            onClick={async () => {
              setOverlayLaunching(true)
              try {
                const res = await fetch(`${API_BASE}/overlay/launch`, { method: 'POST' })
                const d = await res.json().catch(() => ({}))
                if (!res.ok) throw new Error(d.detail || 'Failed to launch')
              } catch (e) {
                alert(e.message || 'Failed to launch overlay')
              } finally {
                setOverlayLaunching(false)
              }
            }}
            disabled={overlayLaunching}
            className="text-sm px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-slate-100 border border-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Launch the always-on-top game overlay for chatting while gaming"
          >
            {overlayLaunching ? 'Launching…' : 'Game Overlay'}
          </button>
        </div>
      </header>

      {/* Body: left nav sidebar + main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar */}
        <nav className="w-20 border-r border-slate-800 flex flex-col items-center pt-4 gap-1 flex-shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-16 py-3 rounded-xl text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-emerald-600 text-white'
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Main Content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {activeTab === 'chat' ? (
            <div className="flex-1 flex flex-col overflow-hidden min-w-0">
              <ChatTab />
            </div>
          ) : activeTab === 'journal' ? (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <JournalTab />
            </main>
          ) : activeTab === 'notes' ? (
            <NotesTab />
          ) : activeTab === 'core' ? (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <CoreMemoryTab />
            </main>
          ) : activeTab === 'cron' ? (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <CronTab />
            </main>
          ) : activeTab === 'data' ? (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <DataTab />
            </main>
          ) : activeTab === 'tools' ? (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <ToolsTab />
            </main>
          ) : (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <HeartbeatTab />
            </main>
          )}
        </div>
      </div>
    </div>
  )
}

export default App

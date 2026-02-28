import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import Picker from '@emoji-mart/react'
import emojiData from '@emoji-mart/data'

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
function CronJobCard({ job, onEdit, onPause, onResume, onClone, onDelete }) {
  const [showConfirmDelete, setShowConfirmDelete] = useState(false)

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

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-2.5 h-2.5 rounded-full ${getStatusColor(job.status)}`} />
          <h3 className="text-lg font-semibold text-slate-100">{job.name}</h3>
          {job.is_one_time && (
            <span className="text-xs bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded">
              One-time
            </span>
          )}
          {job.created_by === 'agent' && (
            <span className="text-xs bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded">
              Agent
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
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
            className="px-3 py-1.5 text-sm bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors"
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
              className="px-3 py-1.5 text-sm bg-red-600/20 text-red-300 rounded-lg hover:bg-red-600/30 transition-colors"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {/* Description */}
      {job.description && (
        <p className="text-sm text-slate-400 mb-3">{job.description}</p>
      )}

      {/* Instructions preview */}
      <div className="bg-slate-900/50 rounded-lg p-3 mb-3">
        <p className="text-xs text-slate-500 mb-1">Instructions:</p>
        <p className="text-sm text-slate-300 line-clamp-3">{job.instructions}</p>
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
      if (!res.ok) throw new Error('Failed to delete job')
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
              />
            ))}
          </div>
        )}
      </div>
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
  }

  const blockDescriptions = {
    system_instructions: 'Read-only system instructions for the agent.',
    user: 'Information about the user that the agent should remember.',
    identity: "The agent's identity, personality, and self-concept.",
    ideaspace: 'Working memory for ongoing thoughts and ideas.',
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

  const blockOrder = ['system_instructions', 'user', 'identity', 'ideaspace']

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
function ChatTab() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const messagesEndRef = useRef(null)
  const loadingRef = useRef(false)
  const inputRef = useRef(null)
  const emojiPickerRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

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
    if (!text || loading) return

    setInput('')
    setError(null)
    loadingRef.current = true
    setLoading(true)
    // Optimistically show user message while waiting for LLM
    setMessages((prev) => [...prev, { role: 'user', content: text, metadata: { role_display: 'User' } }])

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, thread_id: 'main' }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      // Reload from DB to get the actual saved messages (user + assistant)
      await loadHistory()
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

  const visibleMessages = messages.filter((m) => m.role !== 'tool')

  return (
    <>
      {/* Messages */}
      <main className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl mx-auto space-y-6">
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
                    <p className="whitespace-pre-wrap break-words">{msg.content ?? msg.error}</p>
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
        <div className="max-w-2xl mx-auto flex gap-3 relative">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            disabled={loading}
            className="flex-1 rounded-xl bg-slate-800/80 border border-slate-700 px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50 disabled:opacity-50"
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
            disabled={loading || !input.trim()}
            className="rounded-xl bg-emerald-600 px-5 py-3 font-medium text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </div>
        {error && (
          <p className="max-w-2xl mx-auto mt-2 text-sm text-red-400">{error}</p>
        )}
      </footer>
    </>
  )
}

// ==================== MAIN APP ====================

const TABS = [
  { id: 'chat', label: 'Chat' },
  { id: 'core', label: 'Core' },
  { id: 'cron', label: 'Cron' },
]

// Main App Component
function App() {
  const [activeTab, setActiveTab] = useState('chat')

  return (
    <div className="h-screen bg-slate-950 text-slate-100 flex flex-col overflow-hidden">
      {/* Header — title only */}
      <header className="border-b border-slate-800 flex-shrink-0">
        <div className="px-5 py-3">
          <h1 className="text-xl font-semibold text-slate-100">Agent</h1>
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
            <ChatTab />
          ) : activeTab === 'core' ? (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <CoreMemoryTab />
            </main>
          ) : (
            <main className="flex-1 overflow-y-auto px-6 py-6">
              <CronTab />
            </main>
          )}
        </div>
      </div>
    </div>
  )
}

export default App

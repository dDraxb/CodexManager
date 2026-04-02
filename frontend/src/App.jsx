import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const REFRESH_OPTIONS = [5, 10, 20, 30]
const ARCHIVE_STATUSES = new Set(['finished', 'failed', 'stopped', 'lost'])

const EMPTY_CREATE_FORM = {
  name: '',
  repoPath: '',
  profile: 'safe-edit',
  prompt: '',
  createWorktreeForWrites: false,
  autoInitGit: false,
  requireChangelog: false,
  launch: true
}

const EMPTY_ADOPT_FORM = {
  name: '',
  codexSessionId: '',
  repoPath: '',
  profile: 'read-only'
}

const COMMAND_TABS = [
  { id: 'create', label: 'New session' },
  { id: 'adopt', label: 'Adopt session' },
  { id: 'cleanup', label: 'Cleanup' }
]

const ANSI_PATTERN = /\u001b\[[0-9;?]*[ -/]*[@-~]/g

function badgeClass(status) {
  const map = {
    running: 'badge badge-running',
    waiting_input: 'badge badge-waiting',
    idle: 'badge badge-idle',
    failed: 'badge badge-failed',
    stopped: 'badge badge-stopped',
    lost: 'badge badge-failed',
    created: 'badge badge-stopped',
    starting: 'badge badge-idle',
    finished: 'badge badge-running'
  }
  return map[status] || 'badge'
}

function healthBadgeClass(label) {
  const map = {
    healthy: 'badge badge-running',
    monitor: 'badge badge-idle',
    attention: 'badge badge-failed'
  }
  return map[label] || 'badge badge-stopped'
}

function healthLabel(label) {
  if (!label) return 'monitor'
  return label
}

function priorityBadgeClass(score) {
  if (score >= 90) return 'badge badge-failed'
  if (score >= 60) return 'badge badge-waiting'
  return 'badge badge-stopped'
}

function priorityLabel(score) {
  if (score >= 90) return 'priority high'
  if (score >= 60) return 'priority medium'
  return 'priority low'
}

function attachmentBadgeClass(state) {
  return state === 'attached' ? 'badge badge-attached' : 'badge badge-detached'
}

function validationBadgeClass(status) {
  const map = {
    passed: 'badge badge-running',
    failed: 'badge badge-failed',
    running: 'badge badge-waiting',
    unknown: 'badge badge-stopped'
  }
  return map[status] || 'badge badge-stopped'
}

function validationLabel(kind, status) {
  if (status === 'unknown') {
    return kind === 'tests' ? 'No recent test activity' : 'No recent lint activity'
  }
  if (status === 'running') {
    return kind === 'tests' ? 'Test activity active' : 'Lint activity active'
  }
  return `${kind === 'tests' ? 'Tests' : 'Lint'} ${status}`
}

function validationActivityLabel(kind, activity) {
  if (activity === 'active') {
    return kind === 'tests' ? 'Test activity active now' : 'Lint activity active now'
  }
  return kind === 'tests' ? 'No recent test activity' : 'No recent lint activity'
}

function validationResultLabel(kind, status) {
  if (status === 'unknown') {
    return kind === 'tests' ? 'No recent test result' : 'No recent lint result'
  }
  return `${kind === 'tests' ? 'Latest test result' : 'Latest lint result'}: ${status}`
}

function formatValidationTimestamp(timestamp) {
  if (!timestamp) return null
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString()
}

function validationResultDetail(kind, status, timestamp) {
  if (status === 'unknown') {
    return kind === 'tests' ? 'No known test result yet' : 'No known lint result yet'
  }
  const formatted = formatValidationTimestamp(timestamp)
  return formatted
    ? `${kind === 'tests' ? 'Latest test result' : 'Latest lint result'}: ${status} at ${formatted}`
    : validationResultLabel(kind, status)
}

function blockCategoryLabel(category) {
  const map = {
    approval: 'Approval',
    input: 'User input',
    environment: 'Environment',
    dependency: 'Dependency',
    network: 'Network',
    filesystem: 'Filesystem',
    tooling: 'Tooling',
    unknown: 'Unknown'
  }
  return map[category] || 'Unknown'
}

function phaseBadgeClass(phase) {
  const map = {
    planning: 'badge badge-idle',
    reading: 'badge badge-idle',
    editing: 'badge badge-running',
    testing: 'badge badge-waiting',
    blocked: 'badge badge-failed',
    waiting_input: 'badge badge-waiting',
    reviewing: 'badge badge-stopped',
    completed: 'badge badge-running',
    unknown: 'badge badge-stopped'
  }
  return map[phase] || 'badge badge-stopped'
}

function phaseLabel(phase) {
  if (!phase || phase === 'unknown') return 'Unknown'
  return String(phase).replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function phaseConfidenceLabel(confidence) {
  if (!confidence) return 'low confidence'
  return `${confidence} confidence`
}

function phaseReasonText(status, currentReason, lastMajorReason) {
  if (status === 'running' || status === 'starting' || status === 'waiting_input') {
    return currentReason || 'No phase evidence recorded yet'
  }
  return lastMajorReason || currentReason || 'No phase evidence recorded yet'
}

function phaseContextLabel(status, phase) {
  const label = phaseLabel(phase)
  if (!phase || phase === 'unknown') {
    return 'Phase not established yet'
  }
  if (status === 'running' || status === 'starting' || status === 'waiting_input') {
    return `Current phase: ${label}`
  }
  return `Last major phase: ${label}`
}

function majorPhaseContextLabel(status, currentPhase, lastMajorPhase) {
  if (status === 'running' || status === 'starting' || status === 'waiting_input') {
    return phaseContextLabel(status, currentPhase)
  }
  if (lastMajorPhase && lastMajorPhase !== 'unknown') {
    return `Last major phase: ${phaseLabel(lastMajorPhase)}`
  }
  return phaseContextLabel(status, currentPhase)
}

function phaseTimelineSummary(entries) {
  if (!entries.length) {
    return 'No phase transitions recorded yet'
  }
  if (entries.length === 1) {
    return `Only observed phase: ${phaseLabel(entries[0].phase)}`
  }
  return entries.map((entry) => phaseLabel(entry.phase)).join(' -> ')
}

function formatEventTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp
  return date.toLocaleString()
}

function stateTimelineEntry(event) {
  const metadata = parseEventMetadata(event)
  if (event.type === 'status_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Status',
      value: event.message.replace('Status -> ', '').trim(),
      detail: metadata.note || null
    }
  }
  if (event.type === 'work_phase_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Phase',
      value: `${phaseLabel(metadata.work_phase || event.message.replace('Phase -> ', '').trim().toLowerCase())} · ${phaseConfidenceLabel(metadata.confidence || 'low')}`,
      detail: metadata.reason || null
    }
  }
  if (event.type === 'validation_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Validation',
      value: event.message,
      detail: null
    }
  }
  if (event.type === 'validation_activity_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Validation activity',
      value: event.message,
      detail: null
    }
  }
  if (event.type === 'health_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Health',
      value: `${healthLabel(metadata.health_label || event.message.replace('Health -> ', '').trim())} · ${metadata.health_reason || ''}`.trim(),
      detail: metadata.health_evidence || null
    }
  }
  if (event.type === 'priority_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Priority',
      value: metadata.priority_reason || event.message,
      detail: metadata.priority_evidence || null
    }
  }
  if (event.type === 'repo_risk_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Repo risk',
      value: metadata.repo_risk_reason || event.message,
      detail: null
    }
  }
  if (event.type === 'attachment_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Attachment',
      value: event.message,
      detail: null
    }
  }
  return null
}

function parseEventMetadata(event) {
  if (!event?.metadata_json) return {}
  try {
    return JSON.parse(event.metadata_json)
  } catch {
    return {}
  }
}

function parseJsonList(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.filter(Boolean)
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed.filter(Boolean) : []
  } catch {
    return []
  }
}

function overlapPreviewText(count, preview) {
  const paths = parseJsonList(preview)
  if (!count || !paths.length) return null
  const shown = paths.slice(0, 3).join(', ')
  if (count > paths.length) {
    return `${shown}, +${count - paths.length} more`
  }
  return shown
}

function operationalSummary(session) {
  if (!session) return 'No session selected.'
  const parts = []
  if (session.status === 'running' || session.status === 'starting' || session.status === 'waiting_input') {
    parts.push(phaseContextLabel(session.status, session.work_phase || 'unknown'))
  } else {
    parts.push(majorPhaseContextLabel(session.status, session.work_phase || 'unknown', session.last_major_phase || 'unknown'))
  }
  if (session.health_reason) {
    parts.push(`health says ${session.health_reason}`)
  }
  if (session.priority_reason && session.priority_reason !== 'stable background session' && session.priority_reason !== 'priority not established') {
    parts.push(`priority is ${session.priority_reason}`)
  }
  if (session.repo_overlap_count > 0) {
    parts.push(`shared file overlap on ${overlapPreviewText(session.repo_overlap_count, session.repo_overlap_preview)}`)
  }
  if (!parts.length) {
    return 'No operational summary available yet.'
  }
  const [first, ...rest] = parts
  return rest.length ? `${first}; ${rest.join('; ')}` : first
}

function formatError(err) {
  return err instanceof Error ? err.message : 'Unexpected request error'
}

async function fetchJson(url, options) {
  const res = await fetch(url, options)
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}))
    throw new Error(payload.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

function isArchivedSession(session) {
  return ARCHIVE_STATUSES.has(session.status)
}

function buildCreatePayload(form) {
  return {
    name: form.name.trim(),
    repoPath: form.repoPath.trim(),
    profile: form.profile,
    prompt: form.prompt.trim() || null,
    createWorktreeForWrites: form.createWorktreeForWrites,
    autoInitGit: form.autoInitGit,
    requireChangelog: form.requireChangelog,
    launch: form.launch
  }
}

function buildAdoptPayload(form) {
  return {
    name: form.name.trim(),
    codexSessionId: form.codexSessionId.trim(),
    repoPath: form.repoPath.trim(),
    profile: form.profile
  }
}

function sanitizeLogLine(line) {
  return String(line).replaceAll(ANSI_PATTERN, '').replaceAll('\r', '')
}

function trimTrailingBlankLines(lines) {
  const trimmed = [...lines]
  while (trimmed.length > 0 && !trimmed[trimmed.length - 1].trim()) {
    trimmed.pop()
  }
  return trimmed
}

function formatCodexTimestamp(epochSeconds) {
  if (!epochSeconds) return 'unknown time'
  return new Date(epochSeconds * 1000).toLocaleString()
}

function secondsSince(timestamp) {
  if (!timestamp) return null
  const parsed = Date.parse(timestamp)
  if (Number.isNaN(parsed)) return null
  return Math.max(0, Math.floor((Date.now() - parsed) / 1000))
}

function formatDuration(seconds) {
  if (seconds == null) return null
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

function activityLabel(session) {
  if (!session) return 'No activity yet'
  if (session.status === 'idle') {
    const seconds = secondsSince(session.output_observed_at || session.last_activity_at)
    const formatted = formatDuration(seconds)
    return formatted ? `Idle for ${formatted}` : (session.last_known_activity || 'Idle')
  }
  return session.last_known_activity || 'No activity yet'
}

export default function App() {
  const [summary, setSummary] = useState({ total: 0, counts: {}, needsAttention: 0 })
  const [sessions, setSessions] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [events, setEvents] = useState([])
  const [logs, setLogs] = useState([])
  const [refresh, setRefresh] = useState(10)
  const [error, setError] = useState('')
  const [toast, setToast] = useState(null)
  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM)
  const [adoptForm, setAdoptForm] = useState(EMPTY_ADOPT_FORM)
  const [showCreateAdvanced, setShowCreateAdvanced] = useState(false)
  const [showArchive, setShowArchive] = useState(false)
  const [sessionQuery, setSessionQuery] = useState('')
  const [commandTab, setCommandTab] = useState('create')
  const [showCommandPanel, setShowCommandPanel] = useState(false)
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyThreads, setHistoryThreads] = useState([])
  const [resumePoints, setResumePoints] = useState([])
  const [showResumeChooser, setShowResumeChooser] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [fastPollUntil, setFastPollUntil] = useState(0)
  const [trendPanelHeight, setTrendPanelHeight] = useState(null)
  const logOutputRef = useRef(null)
  const activityCardRef = useRef(null)
  const stickLogToBottomRef = useRef(true)
  const previousSelectedIdRef = useRef(null)
  const fastPollSessionIdRef = useRef(null)
  const fastPollExtendedRef = useRef(false)
  const previousLogSignatureRef = useRef('')
  const detailRequestRef = useRef(0)
  const loadedDetailSessionRef = useRef(null)

  const deferredQuery = useDeferredValue(sessionQuery)
  const normalizedQuery = deferredQuery.trim().toLowerCase()

  const visibleSessions = useMemo(() => {
    return sessions.filter((session) => {
      if (!showArchive && isArchivedSession(session)) {
        return false
      }
      if (!normalizedQuery) {
        return true
      }
      return [
        session.name,
        session.target_label,
        session.profile,
        session.status,
        session.work_phase,
        session.branch
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery))
    }).sort((left, right) => {
      const priorityDelta = (right.priority_score || 0) - (left.priority_score || 0)
      if (priorityDelta !== 0) return priorityDelta
      return (right.updated_at || '').localeCompare(left.updated_at || '')
    })
  }, [normalizedQuery, sessions, showArchive])

  const selectedSession = useMemo(
    () => visibleSessions.find((session) => session.id === selectedId) || sessions.find((session) => session.id === selectedId) || null,
    [selectedId, sessions, visibleSessions]
  )
  const canAct = !!selectedSession
  const canAttach = !!selectedSession && !(selectedSession.mode === 'adopted' && !selectedSession.started_at)
  const canResumeFromHistory = !!selectedSession?.codex_session_id && !canAttach
  const pollIntervalSeconds = Date.now() < fastPollUntil ? 2 : refresh
  const phaseTimeline = useMemo(() => {
    const rawTimeline = events
      .filter((event) => event.type === 'work_phase_changed')
      .map((event) => {
        const metadata = parseEventMetadata(event)
        return {
          id: event.id,
          timestamp: event.timestamp,
          phase: metadata.work_phase || event.message.replace('Phase -> ', '').trim().toLowerCase(),
          confidence: metadata.confidence || 'low'
        }
      })
    return rawTimeline.filter((entry, index) => index === 0 || entry.phase !== rawTimeline[index - 1].phase)
  }, [events])
  const stateTimeline = useMemo(() => {
    const entries = events
      .map((event) => stateTimelineEntry(event))
      .filter(Boolean)
    return entries.filter((entry, index) => {
      const previous = entries[index - 1]
      if (!previous) return true
      return !(previous.label === entry.label && previous.value === entry.value && previous.detail === entry.detail)
    })
  }, [events])

  useEffect(() => {
    const nextVisible = visibleSessions[0] || null
    const selectedStillVisible = visibleSessions.some((session) => session.id === selectedId)

    if (visibleSessions.length === 0) {
      setSelectedId(sessions[0]?.id || null)
      if (sessions.length === 0) {
        setDetail(null)
        setEvents([])
        setLogs([])
      }
      return
    }

    if (!selectedId || !selectedStillVisible) {
      setSelectedId(nextVisible?.id || null)
    }
  }, [selectedId, sessions, visibleSessions])

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(id)
  }, [toast])

  function notify(type, message) {
    setToast({ type, message })
  }

  async function runRequest(work, successMessage, options = {}) {
    const { rethrow = false } = options
    try {
      setError('')
      const result = await work()
      if (successMessage) {
        notify('success', successMessage(result))
      }
      return result
    } catch (err) {
      const message = formatError(err)
      setError(message)
      notify('error', message)
      if (rethrow) {
        throw err
      }
      return null
    }
  }

  async function loadAll() {
    try {
      setError('')
      const [nextSummary, rows] = await Promise.all([fetchJson('/api/summary'), fetchJson('/api/sessions')])
      startTransition(() => {
        setSummary(nextSummary)
        setSessions(rows)
      })
    } catch (err) {
      const message = formatError(err)
      setError(message)
      notify('error', message)
    }
  }

  async function loadDetail(id) {
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    if (!id) {
      loadedDetailSessionRef.current = null
      setDetail(null)
      setEvents([])
      setLogs([])
      return
    }
    if (loadedDetailSessionRef.current !== id) {
      startTransition(() => {
        setDetail(null)
        setEvents([])
        setLogs([])
      })
    }
    try {
      const [nextDetail, nextEvents, nextLogs] = await Promise.all([
        fetchJson(`/api/sessions/${id}`),
        fetchJson(`/api/sessions/${id}/events?limit=25`),
        fetchJson(`/api/sessions/${id}/logs?tail=120`)
      ])
      if (detailRequestRef.current !== requestId) {
        return
      }
      loadedDetailSessionRef.current = id
      startTransition(() => {
        setDetail(nextDetail)
        setEvents(nextEvents)
        setLogs(trimTrailingBlankLines((nextLogs.lines || []).map(sanitizeLogLine)))
      })
    } catch (err) {
      if (detailRequestRef.current !== requestId) {
        return
      }
      const message = formatError(err)
      if (message.toLowerCase().includes('session not found')) {
        loadedDetailSessionRef.current = null
        setSelectedId(null)
        return
      }
      setError(message)
      notify('error', message)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  useEffect(() => {
    loadDetail(selectedId)
  }, [selectedId])

  useEffect(() => {
    const interval = setInterval(() => {
      loadAll()
      if (selectedId) loadDetail(selectedId)
    }, pollIntervalSeconds * 1000)
    return () => clearInterval(interval)
  }, [pollIntervalSeconds, selectedId])

  useEffect(() => {
    if (Date.now() >= fastPollUntil) return
    const timeout = setTimeout(() => setFastPollUntil(0), Math.max(0, fastPollUntil - Date.now()))
    return () => clearTimeout(timeout)
  }, [fastPollUntil])

  useEffect(() => {
    if (!selectedId) {
      previousLogSignatureRef.current = ''
      return
    }

    const currentLogSignature = logs.slice(-6).join('\n')
    const currentStatus = detail?.status || null
    const sameSession = fastPollSessionIdRef.current === selectedId
    const fastPollingActive = Date.now() < fastPollUntil
    const observedNewActivity =
      previousLogSignatureRef.current !== '' &&
      (currentLogSignature !== previousLogSignatureRef.current || currentStatus === 'running')

    if (sameSession && fastPollingActive && !fastPollExtendedRef.current && observedNewActivity) {
      fastPollExtendedRef.current = true
      setFastPollUntil(Date.now() + 120_000)
    }

    previousLogSignatureRef.current = currentLogSignature
  }, [detail?.status, fastPollUntil, logs, selectedId])

  useEffect(() => {
    if (!logOutputRef.current) return
    const switchedSessions = previousSelectedIdRef.current !== selectedId
    previousSelectedIdRef.current = selectedId
    if (switchedSessions || stickLogToBottomRef.current) {
      logOutputRef.current.scrollTop = logOutputRef.current.scrollHeight
    }
  }, [logs])

  useEffect(() => {
    const node = activityCardRef.current
    if (!node) return

    const updateHeight = () => {
      setTrendPanelHeight(node.getBoundingClientRect().height || null)
    }

    updateHeight()
    const observer = new ResizeObserver(() => updateHeight())
    observer.observe(node)
    window.addEventListener('resize', updateHeight)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', updateHeight)
    }
  }, [detail, events.length, logs.length, selectedId, sessions.length])

  function handleLogScroll(event) {
    const node = event.currentTarget
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight
    stickLogToBottomRef.current = distanceFromBottom <= 8
  }

  const chartData = visibleSessions.slice(0, 12).map((session) => ({
    name: session.name,
    changed: session.changed_files_count,
    attention: session.needs_attention
  }))

  async function copyOrNotify(command, successLabel) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(command)
        notify('success', successLabel)
        return
      }
    } catch (_err) {
      // Clipboard access can be blocked in browser privacy modes.
    }
    notify('success', `Command: ${command}`)
  }

  async function refreshAfterMutation(nextSelectedId = selectedId) {
    await loadAll()
    if (nextSelectedId) {
      setSelectedId(nextSelectedId)
      await loadDetail(nextSelectedId)
      return
    }
    setDetail(null)
    setEvents([])
    setLogs([])
  }

  function startFastPolling(durationMs = 60_000) {
    fastPollSessionIdRef.current = selectedId
    fastPollExtendedRef.current = false
    setFastPollUntil(Date.now() + durationMs)
  }

  async function runAction(action) {
    if (!selectedSession) {
      notify('error', 'Select a session first')
      return
    }

    if (action === 'attach') {
      const payload = await runRequest(
        () => fetchJson(`/api/sessions/${selectedSession.id}/open`, { method: 'POST' }),
        () => 'Attach command copied to clipboard'
      )
      if (!payload) return
      await copyOrNotify(payload.command, 'Attach command copied to clipboard')
      startFastPolling()
      await loadAll()
      await loadDetail(selectedSession.id)
      return
    }

    if (action === 'resume') {
      const payload = await runRequest(
        () => fetchJson(`/api/sessions/${selectedSession.id}/resume`, { method: 'POST' }),
        () => `History resume ready for ${selectedSession.name}`
      )
      if (!payload) return
      await copyOrNotify(payload.command, 'History resume attach command copied to clipboard')
      await refreshAfterMutation(selectedSession.id)
      return
    }

    if (action === 'stop') {
      await runRequest(
        () => fetchJson(`/api/sessions/${selectedSession.id}/stop`, { method: 'POST' }),
        () => `Stopped ${selectedSession.name}`
      )
      await refreshAfterMutation(selectedSession.id)
      return
    }

    if (action === 'delete') {
      await runRequest(
        () => fetchJson(`/api/sessions/${selectedSession.id}`, { method: 'DELETE' }),
        () => `Deleted ${selectedSession.name}`
      )
      await refreshAfterMutation(null)
    }
  }

  async function loadCodexHistory(query = historyQuery) {
    setLoadingHistory(true)
    try {
      const trimmedQuery = query.trim()
      const threadId = adoptForm.codexSessionId.trim()
      const repoPath = adoptForm.repoPath.trim()
      const url = threadId
        ? `/api/codex/resume-points?limit=12&thread_id=${encodeURIComponent(threadId)}&cwd=${encodeURIComponent(repoPath)}&prompt=${encodeURIComponent(trimmedQuery)}`
        : `/api/codex/history?limit=12&query=${encodeURIComponent(trimmedQuery)}&cwd=${encodeURIComponent(repoPath)}`
      const payload = await fetchJson(url)
      setHistoryThreads(payload.threads || [])
    } catch (err) {
      const message = formatError(err)
      setError(message)
      notify('error', message)
    } finally {
      setLoadingHistory(false)
    }
  }

  async function loadResumePoints(sessionId = selectedSession?.id) {
    if (!sessionId) return
    setLoadingHistory(true)
    try {
      const payload = await fetchJson(`/api/sessions/${sessionId}/resume-points?limit=12`)
      setResumePoints(payload.threads || [])
      setShowResumeChooser(true)
    } catch (err) {
      const message = formatError(err)
      setError(message)
      notify('error', message)
    } finally {
      setLoadingHistory(false)
    }
  }

  async function useResumePoint(thread) {
    if (!selectedSession) return
    const payload = await runRequest(
      () =>
        fetchJson(`/api/sessions/${selectedSession.id}/codex-session-link`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            codexSessionId: thread.id,
            codexRolloutPath: thread.rollout_path || null,
            codexUpdatedAt: thread.updated_at || null
          })
        }),
      () => `Resume target updated to ${thread.id}`
    )
    if (!payload) return
    setShowResumeChooser(false)
    await refreshAfterMutation(selectedSession.id)
  }

  function adoptFromHistory(thread) {
    setCommandTab('adopt')
    setAdoptForm((prev) => ({
      ...prev,
      codexSessionId: thread.id,
      repoPath: thread.cwd || prev.repoPath,
      name: prev.name || (thread.title || `imported-${thread.id.slice(0, 8)}`).slice(0, 60)
    }))
    notify('success', `Loaded ${thread.id} into adopt form`)
  }

  function onCreateField(field, value) {
    setCreateForm((prev) => ({ ...prev, [field]: value }))
  }

  function onAdoptField(field, value) {
    setAdoptForm((prev) => ({ ...prev, [field]: value }))
  }

  async function createSession(event) {
    event.preventDefault()
    const payload = buildCreatePayload(createForm)
    if (!payload.name) {
      notify('error', 'Session name is required')
      return
    }

    const session = await runRequest(
      () =>
        fetchJson('/api/sessions/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }),
      (result) => `Created session ${result.name}`,
      { rethrow: true }
    )
    setCreateForm((prev) => ({ ...EMPTY_CREATE_FORM, repoPath: prev.repoPath }))
    await refreshAfterMutation(session.id)
  }

  async function adoptSession(event) {
    event.preventDefault()
    const payload = buildAdoptPayload(adoptForm)
    if (!payload.name || !payload.codexSessionId || !payload.repoPath) {
      notify('error', 'Name, Codex session id, and repo path are required')
      return
    }

    const session = await runRequest(
      () =>
        fetchJson('/api/sessions/adopt', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }),
      (result) => `Adopted session ${result.name}`,
      { rethrow: true }
    )
    setAdoptForm((prev) => ({ ...EMPTY_ADOPT_FORM, repoPath: prev.repoPath }))
    await refreshAfterMutation(session.id)
  }

  async function bulkDelete(kind) {
    const endpoint =
      kind === 'stopped' ? '/api/sessions/bulk-delete/stopped' : '/api/sessions/bulk-delete/test-named'
    const label =
      kind === 'stopped' ? 'Removed stopped sessions' : 'Removed test-named sessions'

    await runRequest(
      () => fetchJson(endpoint, { method: 'POST' }),
      (result) => `${label}: ${result.count}`
    )
    await refreshAfterMutation(null)
  }

  const activeCount = sessions.filter((session) => !isArchivedSession(session)).length
  const archivedCount = sessions.filter((session) => isArchivedSession(session)).length

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <p className="eyebrow">Operations cockpit</p>
          <h1>codex-session-manager</h1>
          <p className="subtitle">Control plane in one place. Execution routed where tmux and codex actually live.</p>
        </div>
        <div className="controls">
          <label>
            Refresh
            <select value={refresh} onChange={(event) => setRefresh(Number(event.target.value))}>
              {REFRESH_OPTIONS.map((seconds) => (
                <option key={seconds} value={seconds}>{seconds}s</option>
              ))}
            </select>
          </label>
          <button onClick={() => loadAll()}>Refresh now</button>
        </div>
      </header>

      <section className="snapshot">
        <div>
          <span className="snapshot-label">Live snapshot</span>
          <strong>{new Date().toLocaleTimeString()}</strong>
        </div>
        <div className="snapshot-metrics">
          <span>{summary.total} total</span>
          <span>{summary.counts.running || 0} running</span>
          <span>{summary.counts.waiting_input || 0} waiting</span>
          <span>{summary.needsAttention || 0} need attention</span>
        </div>
      </section>

      {toast ? <section className={`toast toast-${toast.type}`}>{toast.message}</section> : null}
      {error ? <section className="error">{error}</section> : null}

      <section className="command-panel">
        <article className="command-card command-module">
          <div className="command-module-head">
            <div>
              <p className="eyebrow">Session Controls</p>
              <h2>{commandTab === 'create' ? 'Create and manage sessions' : commandTab === 'adopt' ? 'Adopt existing Codex work' : 'Review and clean archived sessions'}</h2>
            </div>
            <div className="command-head-actions">
              <button
                type="button"
                className="command-toggle"
                aria-expanded={showCommandPanel}
                onClick={() => setShowCommandPanel((value) => !value)}
              >
                {showCommandPanel ? 'Hide controls' : 'Show controls'}
              </button>
              {showCommandPanel ? (
                <div className="command-tabs" role="tablist" aria-label="Session actions">
                  {COMMAND_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={commandTab === tab.id}
                      className={`tab-button ${commandTab === tab.id ? 'active' : ''}`}
                      onClick={() => setCommandTab(tab.id)}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
          {!showCommandPanel ? (
            <div className="command-collapsed-note">
              <p className="muted">Create, adopt, and cleanup controls are hidden until you expand this panel.</p>
            </div>
          ) : null}

          {showCommandPanel && commandTab === 'create' ? (
            <div className="command-pane">
              <div className="command-head">
                <div>
                  <p className="eyebrow">Quick Start Session</p>
                  <h2>Managed session</h2>
                </div>
                <span className="badge badge-idle">{createForm.profile}</span>
              </div>
              <form className="stack-form" onSubmit={createSession}>
                <div className="command-form-grid">
                  <input placeholder="Session name" value={createForm.name} onChange={(event) => onCreateField('name', event.target.value)} />
                  <input placeholder="Working directory (optional absolute)" value={createForm.repoPath} onChange={(event) => onCreateField('repoPath', event.target.value)} />
                </div>
                <textarea placeholder="Prompt (optional)" rows="3" value={createForm.prompt} onChange={(event) => onCreateField('prompt', event.target.value)} />
                <div className="command-settings-grid">
                  <label className="field">
                    <span>Permissions profile</span>
                    <select value={createForm.profile} onChange={(event) => onCreateField('profile', event.target.value)}>
                      <option value="read-only">read-only</option>
                      <option value="safe-edit">safe-edit</option>
                      <option value="full-agent">full-agent</option>
                    </select>
                  </label>
                  <div className="helper-copy">
                    <span className="field-label">What this controls</span>
                    <p className="muted">This controls Codex permissions and approval behavior. Leave the working directory blank to start in the runner home directory.</p>
                  </div>
                  <label className="toggle toggle-inline">
                    <input type="checkbox" checked={createForm.launch} onChange={(event) => onCreateField('launch', event.target.checked)} />
                    <span>Launch in tmux immediately</span>
                  </label>
                </div>

                <button
                  type="button"
                  className="ghost"
                  onClick={() => setShowCreateAdvanced((value) => !value)}
                >
                  {showCreateAdvanced ? 'Hide advanced options' : 'Show advanced options'}
                </button>

                {showCreateAdvanced ? (
                  <div className="advanced-box advanced-grid">
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={createForm.createWorktreeForWrites}
                        onChange={(event) => onCreateField('createWorktreeForWrites', event.target.checked)}
                      />
                      <span>Create dedicated worktree for writable sessions</span>
                    </label>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={createForm.autoInitGit}
                        onChange={(event) => onCreateField('autoInitGit', event.target.checked)}
                      />
                      <span>Auto-init git when repo is missing</span>
                    </label>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={createForm.requireChangelog}
                        onChange={(event) => onCreateField('requireChangelog', event.target.checked)}
                      />
                      <span>Append CHANGELOG.md entry before work starts</span>
                    </label>
                  </div>
                ) : null}

                <button type="submit" className="primary">Start session</button>
              </form>
            </div>
          ) : null}

          {showCommandPanel && commandTab === 'adopt' ? (
            <div className="command-pane">
              <div className="command-head">
                <div>
                  <p className="eyebrow">Adopt Existing Session</p>
                  <h2>Codex handoff</h2>
                </div>
                <span className="badge badge-stopped">reduced observability</span>
              </div>
              <form className="stack-form" onSubmit={adoptSession}>
                <div className="command-form-grid">
                  <input placeholder="Local session name" value={adoptForm.name} onChange={(event) => onAdoptField('name', event.target.value)} />
                  <input placeholder="Codex session id (cdx_...)" value={adoptForm.codexSessionId} onChange={(event) => onAdoptField('codexSessionId', event.target.value)} />
                </div>
                <input placeholder="Repo path (absolute)" value={adoptForm.repoPath} onChange={(event) => onAdoptField('repoPath', event.target.value)} />
                <div className="command-settings-grid adopt-settings-grid">
                  <label className="field">
                    <span>Permissions profile</span>
                    <select value={adoptForm.profile} onChange={(event) => onAdoptField('profile', event.target.value)}>
                      <option value="read-only">read-only</option>
                      <option value="safe-edit">safe-edit</option>
                      <option value="full-agent">full-agent</option>
                    </select>
                  </label>
                  <div className="helper-copy">
                    <span className="field-label">What to provide</span>
                    <p className="muted">Use the existing Codex session id and the repo path where that work actually lives on the runner host.</p>
                  </div>
                </div>
                <button type="submit" className="primary">Adopt session</button>
              </form>
              <div className="history-browser">
                <div className="row between history-browser-head">
                  <div>
                    <p className="eyebrow">Recent Codex History</p>
                    <p className="muted">
                      {adoptForm.codexSessionId.trim()
                        ? 'Showing candidates for the filled Codex session id, newest first.'
                        : adoptForm.repoPath.trim()
                          ? 'Showing recent Codex threads for the filled repo path, newest first.'
                          : 'Showing global recent Codex threads. Fill repo path or session id to narrow it down.'}
                    </p>
                  </div>
                  <button className="ghost" type="button" onClick={() => loadCodexHistory('')}>Load recent</button>
                </div>
                <div className="inline-fields">
                  <input
                    placeholder="Search by title, prompt, or thread id"
                    value={historyQuery}
                    onChange={(event) => setHistoryQuery(event.target.value)}
                  />
                  <button className="ghost" type="button" onClick={() => loadCodexHistory(historyQuery)}>
                    {loadingHistory ? 'Loading…' : 'Search history'}
                  </button>
                </div>
                <div className="history-list">
                  {historyThreads.map((thread) => (
                    <div key={thread.id} className="history-item">
                      <div className="row between">
                        <strong>{thread.title || thread.first_user_message || thread.id}</strong>
                        <span className="badge badge-stopped">{formatCodexTimestamp(thread.updated_at)}</span>
                      </div>
                      <p className="muted">{thread.id}</p>
                      <p className="muted">{thread.cwd}</p>
                      <button className="ghost" type="button" onClick={() => adoptFromHistory(thread)}>Use in adopt form</button>
                    </div>
                  ))}
                  {!historyThreads.length ? <p className="muted">No history loaded yet.</p> : null}
                </div>
              </div>
            </div>
          ) : null}

          {showCommandPanel && commandTab === 'cleanup' ? (
            <div className="command-pane cleanup-card">
              <div className="command-head">
                <div>
                  <p className="eyebrow">Cleanup</p>
                  <h2>Archive control</h2>
                </div>
              </div>
              <div className="cleanup-stats">
                <div>
                  <strong>{activeCount}</strong>
                  <span>active</span>
                </div>
                <div>
                  <strong>{archivedCount}</strong>
                  <span>archived</span>
                </div>
              </div>
              <label className="toggle">
                <input type="checkbox" checked={showArchive} onChange={(event) => setShowArchive(event.target.checked)} />
                <span>Show archived sessions in the grid</span>
              </label>
              <div className="cleanup-actions">
                <button className="ghost" onClick={() => bulkDelete('stopped')}>Delete all stopped sessions</button>
                <button className="ghost danger" onClick={() => bulkDelete('test-named')}>Delete test-named sessions</button>
              </div>
              <p className="muted">Archived view includes finished, failed, stopped, and lost sessions.</p>
            </div>
          ) : null}
        </article>
      </section>

      <section className="session-grid-section">
        <article className="panel">
          <div className="panel-head">
            <div>
              <h2>Session Grid</h2>
              <p className="muted">Choose a session first, then inspect its details below.</p>
            </div>
            <input
              className="filter-input"
              placeholder="Filter by name, branch, profile..."
              value={sessionQuery}
              onChange={(event) => setSessionQuery(event.target.value)}
            />
          </div>
          <div className="grid-list compact-grid-list">
            {visibleSessions.length === 0 ? <p className="muted">No sessions match the current view.</p> : null}
            {visibleSessions.map((session) => (
              <button
                key={session.id}
                className={`session-card ${session.id === selectedId ? 'selected' : ''}`}
                onClick={() => setSelectedId(session.id)}
              >
                <div className="row between">
                  <strong>{session.name}</strong>
                  <div className="row">
                    <span className={badgeClass(session.status)}>{session.status}</span>
                    <span className={attachmentBadgeClass(session.attachment_state)}>{session.attachment_state || 'detached'}</span>
                  </div>
                </div>
                <p>{session.target_label} · {session.profile}</p>
                <p className="muted">{session.branch || '(no branch)'} · {session.changed_files_count} changed</p>
                <p className="muted">
                  {majorPhaseContextLabel(session.status, session.work_phase || 'unknown', session.last_major_phase || 'unknown')}
                </p>
                <p className="muted">{activityLabel(session)}</p>
              </button>
            ))}
          </div>
        </article>
      </section>

      <section className="cards selected-session-grid">
        <article className="card overview-card">
          <h3>Session Overview</h3>
          <p>{selectedSession?.name || 'No session selected'}</p>
          {selectedSession ? (
            <>
              <div className="focus-badges">
                <span className={badgeClass(selectedSession.status)}>{selectedSession.status}</span>
                <span className={healthBadgeClass(detail?.health_label || selectedSession.health_label || 'monitor')}>
                  {healthLabel(detail?.health_label || selectedSession.health_label || 'monitor')}
                </span>
              </div>
              <p className="summary-line">
                {operationalSummary({
                  ...selectedSession,
                  ...detail,
                })}
              </p>
              <p className="muted">
                Phase confidence: {(
                  selectedSession.status === 'running' || selectedSession.status === 'starting' || selectedSession.status === 'waiting_input'
                    ? (detail?.work_phase_confidence || selectedSession.work_phase_confidence || 'low')
                    : (detail?.last_major_phase_confidence || selectedSession.last_major_phase_confidence || detail?.work_phase_confidence || selectedSession.work_phase_confidence || 'low')
                )}
              </p>
              <p className="muted">
                Phase evidence: {phaseReasonText(
                  selectedSession.status,
                  detail?.work_phase_reason || selectedSession.work_phase_reason,
                  detail?.last_major_phase_reason || selectedSession.last_major_phase_reason
                )}
              </p>
              <p className="muted">Current focus: {(detail?.health_reason || selectedSession.health_reason || 'monitor the session')}</p>
              {detail?.health_evidence || selectedSession.health_evidence ? (
                <p className="muted">Health evidence: {detail?.health_evidence || selectedSession.health_evidence}</p>
              ) : null}
              {((detail?.repo_overlap_count || selectedSession.repo_overlap_count || 0) > 0) ? (
                <p className="muted">
                  Shared file overlap: {overlapPreviewText(
                    detail?.repo_overlap_count || selectedSession.repo_overlap_count || 0,
                    detail?.repo_overlap_preview || selectedSession.repo_overlap_preview
                  )}
                </p>
              ) : null}
              {detail?.block_category ? <p className="muted">Block type: {blockCategoryLabel(detail.block_category)}</p> : null}
              {detail?.block_reason ? <p className="muted">Block reason: {detail.block_reason}</p> : null}
              <div className="overview-grid">
                <div className="overview-item overview-item-wide">
                  <span className="overview-label">Working directory</span>
                  <span className="overview-value">{selectedSession.repo_path}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Branch</span>
                  <span className="overview-value">{detail?.branch || selectedSession.branch || '(default)'}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Changed files</span>
                  <span className="overview-value">{detail?.changed_files_count ?? selectedSession.changed_files_count ?? 0}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Mode</span>
                  <span className="overview-value">{selectedSession.mode}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Profile</span>
                  <span className="overview-value">{selectedSession.profile}</span>
                </div>
                <div className="overview-item overview-item-wide">
                  <span className="overview-label">Execution path</span>
                  <span className="overview-value">{detail?.worktree_path || detail?.repo_path || selectedSession.repo_path}</span>
                </div>
              </div>
            </>
          ) : null}
        </article>
        <article className="panel execution-card execution-panel">
          <h3>Execution</h3>
          <div className="execution-badges">
            <span className="badge badge-stopped">{detail?.profile || '-'}</span>
            <span className="badge badge-stopped">{detail?.approval_policy || '-'}</span>
            <span className={attachmentBadgeClass(detail?.attachment_state)}>{detail?.attachment_state || 'detached'}</span>
          </div>
          <div className="execution-layout">
            <div className="execution-main">
              <div className="execution-section">
                <p className="execution-section-title">Live Transport</p>
                <div className="execution-grid">
                  <div className="execution-item">
                    <span className="execution-label">tmux session</span>
                    <span className="execution-value execution-code">{detail?.tmux_session || '-'}</span>
                  </div>
                  <div className="execution-item">
                    <span className="execution-label">Attach state</span>
                    <span className="execution-value">{detail?.attachment_state || 'detached'}</span>
                  </div>
                </div>
              </div>
              <div className="execution-section">
                <p className="execution-section-title">Codex History Target</p>
                <div className="execution-grid">
                  <div className="execution-item execution-item-wide">
                    <span className="execution-label">Codex session</span>
                    <span className="execution-value execution-code">{detail?.codex_session_id || 'pending capture'}</span>
                  </div>
                  <div className="execution-item execution-item-wide">
                    <span className="execution-label">History file</span>
                    <span className="execution-value execution-code">{detail?.codex_rollout_path || 'not linked yet'}</span>
                  </div>
                  <div className="execution-item">
                    <span className="execution-label">History updated</span>
                    <span className="execution-value">{detail?.codex_updated_at ? formatCodexTimestamp(detail.codex_updated_at) : 'unknown'}</span>
                  </div>
                  <div className="execution-item">
                    <span className="execution-label">Changelog discipline</span>
                    <span className="execution-value">{detail?.require_changelog ? 'required' : 'optional'}</span>
                  </div>
                </div>
              </div>
              {selectedSession?.mode === 'adopted' && !selectedSession?.started_at ? (
                <div className="execution-note">
                  Adopted sessions need `Resume from History` before a live attach command exists.
                </div>
              ) : null}
            </div>
            <div className="execution-side">
              <div className="execution-section execution-actions-panel">
                <p className="execution-section-title">Actions</p>
                <div className="actions execution-actions">
                  <button disabled={!canAttach} onClick={() => runAction('attach')}>Attach Live Session</button>
                  <button disabled={!canResumeFromHistory} onClick={() => runAction('resume')}>Resume from History</button>
                  <button disabled={!canAct} className="ghost" onClick={() => loadResumePoints()}>Choose Resume Point</button>
                  <button disabled={!canAct} className="danger" onClick={() => runAction('stop')}>Stop</button>
                  <button disabled={!canAct} className="danger execution-delete" onClick={() => runAction('delete')}>Delete</button>
                </div>
              </div>
            </div>
          </div>
          {showResumeChooser ? (
            <div className="history-browser resume-browser">
              <div className="row between history-browser-head">
                <div>
                  <p className="eyebrow">Resume Points</p>
                  <p className="muted">Choose the exact Codex thread to resume with `{selectedSession?.name}`.</p>
                </div>
                <button className="ghost" type="button" onClick={() => setShowResumeChooser(false)}>Close</button>
              </div>
              <div className="history-list">
                {resumePoints.map((thread) => (
                  <div key={thread.id} className="history-item">
                    <div className="row between">
                      <strong>{thread.title || thread.first_user_message || thread.id}</strong>
                      <span className={`badge ${detail?.codex_session_id === thread.id ? 'badge-running' : 'badge-stopped'}`}>
                        {detail?.codex_session_id === thread.id ? 'selected' : formatCodexTimestamp(thread.updated_at)}
                      </span>
                    </div>
                    <p className="muted">{thread.id}</p>
                    <p className="muted">{thread.cwd}</p>
                    <button className="ghost" type="button" onClick={() => useResumePoint(thread)}>Use this thread</button>
                  </div>
                ))}
                {!resumePoints.length ? <p className="muted">No resume candidates found for this session yet.</p> : null}
              </div>
            </div>
          ) : null}
        </article>
      </section>

      <section className="main-grid">
        <article ref={activityCardRef} className="card activity-card panel">
          <h3>Activity</h3>
          <p>{activityLabel(detail || selectedSession)}</p>
          <p className="muted">Updated {detail?.updated_at || '-'}</p>
          <p className="muted">Output lines: {logs.length}</p>
          <p className="summary-line">
            {operationalSummary({
              ...(selectedSession || {}),
              ...(detail || {}),
            })}
          </p>
          <p className="muted">Health: {healthLabel(detail?.health_label || selectedSession?.health_label || 'monitor')} · {detail?.health_reason || selectedSession?.health_reason || 'monitor the session'}</p>
          {detail?.health_evidence || selectedSession?.health_evidence ? (
            <p className="muted">Health evidence: {detail?.health_evidence || selectedSession?.health_evidence}</p>
          ) : null}
          {((detail?.repo_overlap_count || selectedSession?.repo_overlap_count || 0) > 0) ? (
            <p className="muted">
              Shared file overlap: {overlapPreviewText(
                detail?.repo_overlap_count || selectedSession?.repo_overlap_count || 0,
                detail?.repo_overlap_preview || selectedSession?.repo_overlap_preview
              )}
            </p>
          ) : null}
          <p className="muted emphasis-line">
            {majorPhaseContextLabel(
              detail?.status || selectedSession?.status || 'idle',
              detail?.work_phase || 'unknown',
              detail?.last_major_phase || 'unknown'
            )} · {phaseConfidenceLabel(
              (detail?.status || selectedSession?.status || 'idle') === 'running' || (detail?.status || selectedSession?.status || 'idle') === 'starting' || (detail?.status || selectedSession?.status || 'idle') === 'waiting_input'
                ? (detail?.work_phase_confidence || 'low')
                : (detail?.last_major_phase_confidence || detail?.work_phase_confidence || 'low')
            )}
          </p>
          <p className="muted">
            Phase evidence: {phaseReasonText(
              detail?.status || selectedSession?.status || 'idle',
              detail?.work_phase_reason,
              detail?.last_major_phase_reason
            )}
          </p>
          {detail?.block_category ? <p className="muted">Block type: {blockCategoryLabel(detail.block_category)}</p> : null}
          {detail?.block_reason ? <p className="muted">Block reason: {detail.block_reason}</p> : null}
          <div className="activity-section">
            <p className="activity-label">Validation</p>
            <p className="muted">{validationActivityLabel('tests', detail?.test_activity || 'none')}</p>
            <p className="muted">{validationResultDetail('tests', detail?.test_status || 'unknown', detail?.test_status_at)}</p>
            <p className="muted">{validationActivityLabel('lint', detail?.lint_activity || 'none')}</p>
            <p className="muted">{validationResultDetail('lint', detail?.lint_status || 'unknown', detail?.lint_status_at)}</p>
          </div>
          <div className="activity-section">
            <p className="activity-label">Recent state changes</p>
            <p className="muted">
              {stateTimeline.length ? `Showing the latest ${Math.min(5, stateTimeline.length)} state transitions` : 'No state transitions recorded yet'}
            </p>
            {stateTimeline.length ? (
              <div className="phase-timeline">
                {stateTimeline.slice(0, 5).map((entry) => (
                  <div key={entry.id} className="phase-timeline-item">
                    <div className="phase-timeline-text">
                      <div className="phase-timeline-main">
                        <strong>{entry.label}</strong>
                        <span className="muted">{entry.value}</span>
                      </div>
                      {entry.detail ? <p className="muted timeline-detail">{entry.detail}</p> : null}
                    </div>
                    <span className="muted">{formatEventTime(entry.timestamp)}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </article>

        <article
          className="panel trend-panel"
          style={trendPanelHeight ? { height: `${Math.round(trendPanelHeight)}px` } : undefined}
        >
          <h2>Changed Files Trend</h2>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d4254" />
                <XAxis dataKey="name" stroke="#7ea3c2" tickFormatter={(value) => value.slice(0, 10)} />
                <YAxis stroke="#7ea3c2" />
                <Tooltip formatter={(value) => [`${value}`, 'Changed files']} />
                <Area type="monotone" dataKey="changed" stroke="#4ee6b8" fill="#4ee6b84d" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="events-section">
          <h2>Recent Events{selectedSession ? ` · ${selectedSession.name}` : ''}</h2>
          <div className="events">
            {!events.length ? <p className="muted">No recent events for the selected session.</p> : null}
            {events.map((event) => (
              <div key={event.id} className="event-item">
                <span>{event.timestamp}</span>
                <strong>{event.type}</strong>
                  <p>{event.message}</p>
                </div>
              ))}
            </div>
          </div>
        </article>
      </section>

      <section className="log-section">
        <article className="panel log-panel">
          <h2>Output Tail</h2>
          <p className="muted">Live pane text for running sessions, file tail for stopped sessions.</p>
          <div ref={logOutputRef} className="log-output" onScroll={handleLogScroll}>
            <pre>{logs.join('\n') || 'No log output available.'}</pre>
          </div>
        </article>
      </section>
    </div>
  )
}

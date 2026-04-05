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

const EMPTY_SKILL_FORM = {
  scope: 'global',
  name: '',
  summary: ''
}

const EMPTY_CONFIG_EDITOR = {
  global: null,
  workspace: null
}

const EMPTY_RULES_EDITOR = {
  global: null,
  workspace: null
}

const EMPTY_AGENT_FORM = {
  name: '',
  summary: ''
}

const EMPTY_AGENT_CONFIG = {
  name: '',
  path: '',
  exists: false,
  content: '',
  backups: []
}

const EMPTY_MCP_FORM = {
  scope: 'global',
  name: '',
  command: '',
  args: ''
}

const COMMAND_TABS = [
  { id: 'create', label: 'New session' },
  { id: 'adopt', label: 'Adopt session' },
  { id: 'cleanup', label: 'Cleanup' },
  { id: 'environment', label: 'Codex environment' }
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
  const labels = {
    tests: ['No recent test activity', 'Test activity active', 'Tests'],
    lint: ['No recent lint activity', 'Lint activity active', 'Lint'],
    build: ['No recent build activity', 'Build activity active', 'Build']
  }
  const [noneLabel, activeLabel, noun] = labels[kind] || labels.tests
  if (status === 'unknown') {
    return noneLabel
  }
  if (status === 'running') {
    return activeLabel
  }
  return `${noun} ${status}`
}

function validationActivityLabel(kind, activity) {
  const labels = {
    tests: ['Test activity active now', 'No recent test activity'],
    lint: ['Lint activity active now', 'No recent lint activity'],
    build: ['Build activity active now', 'No recent build activity']
  }
  const [activeLabel, idleLabel] = labels[kind] || labels.tests
  if (activity === 'active') {
    return activeLabel
  }
  return idleLabel
}

function validationResultLabel(kind, status) {
  const labels = {
    tests: ['No recent test result', 'Latest test result'],
    lint: ['No recent lint result', 'Latest lint result'],
    build: ['No recent build result', 'Latest build result']
  }
  const [noneLabel, resultLabel] = labels[kind] || labels.tests
  if (status === 'unknown') {
    return noneLabel
  }
  return `${resultLabel}: ${status}`
}

function formatValidationTimestamp(timestamp) {
  if (!timestamp) return null
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString()
}

function validationResultDetail(kind, status, timestamp) {
  const labels = {
    tests: ['No known test result yet', 'Latest test result'],
    lint: ['No known lint result yet', 'Latest lint result'],
    build: ['No known build result yet', 'Latest build result']
  }
  const [noneLabel, resultLabel] = labels[kind] || labels.tests
  if (status === 'unknown') {
    return noneLabel
  }
  const formatted = formatValidationTimestamp(timestamp)
  return formatted
    ? `${resultLabel}: ${status} at ${formatted}`
    : validationResultLabel(kind, status)
}

function validationCheckObservedState(kind, session) {
  const activityKey = `${kind}_activity`
  const statusKey = `${kind}_status`
  const activity = session?.[activityKey] || 'none'
  const status = session?.[statusKey] || 'unknown'
  if (activity === 'active') {
    return 'active now'
  }
  if (status === 'unknown') {
    return 'not observed yet'
  }
  return status
}

function validationCheckRequirementLabel(required) {
  return required === false ? 'optional' : 'required'
}

function validationRecipeSourceLabel(recipeId) {
  if (!recipeId) return 'source not established'
  if (recipeId.startsWith('preset:')) {
    return `manager preset · ${recipeId.slice('preset:'.length)}`
  }
  if (recipeId === 'custom-json' || recipeId === 'custom-toml') {
    return 'repo-local custom recipe'
  }
  return `auto-detected · ${recipeId}`
}

function validationHistoryEntryLabel(entry) {
  if (!entry) return 'Unknown validation update'
  const noun = entry.kind === 'lint' ? 'Lint' : entry.kind === 'build' ? 'Build' : 'Tests'
  if (entry.source === 'activity_change') {
    return entry.activity === 'active' ? `${noun} activity started` : `${noun} activity became idle`
  }
  if (entry.status && entry.status !== 'unknown') {
    return `${noun} ${entry.status}`
  }
  return `${noun} updated`
}

function latestGreenValidationLabel(session) {
  if (!session?.last_green_validation_at) return 'No green validation baseline recorded yet'
  const kind = session.last_green_validation_kind || 'validation'
  const formatted = formatValidationTimestamp(session.last_green_validation_at)
  return formatted
    ? `Latest green ${kind}: ${formatted}`
    : `Latest green ${kind}: ${session.last_green_validation_at}`
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

function protectedBranchLabel(state) {
  const map = {
    violation: 'violation',
    protected: 'protected',
    clear: 'clear'
  }
  return map[state] || 'clear'
}

function isolationStateLabel(state) {
  const map = {
    satisfied: 'satisfied',
    required_missing: 'required',
    recommended_missing: 'recommended',
    not_required: 'not required'
  }
  return map[state] || 'not required'
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

function parseValidationRecipe(rawRecipe) {
  if (!rawRecipe) return null
  try {
    const parsed = JSON.parse(rawRecipe)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch (_err) {
    return null
  }
}

function createRecipeDraft(recipe) {
  if (!recipe || !Array.isArray(recipe.checks) || !recipe.checks.length) return null
  return {
    label: recipe.label || 'Custom validation',
    checks: recipe.checks.map((check) => ({
      kind: check.kind,
      label: check.label || phaseLabel(check.kind),
      command: check.command || '',
      required: check.required !== false
    }))
  }
}

function matchRepoPolicyForPath(repoPolicies, repoPath) {
  const normalizedRepoPath = repoPath.trim()
  if (!normalizedRepoPath) return null
  let best = null
  for (const policy of repoPolicies) {
    const prefixes = Array.isArray(policy.path_prefixes) ? policy.path_prefixes : []
    for (const prefix of prefixes) {
      if (!prefix) continue
      if (normalizedRepoPath === prefix || normalizedRepoPath.startsWith(`${String(prefix).replace(/\/+$/, '')}/`)) {
        if (!best || String(prefix).length > String(best.prefix).length) {
          best = { policy, prefix }
        }
      }
    }
  }
  return best?.policy || null
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
  if (event.type === 'validation_drift_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Validation drift',
      value: event.message,
      detail: metadata.changed_since_green_reason || null
    }
  }
  if (event.type === 'review_readiness_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Review readiness',
      value: reviewReadinessLabel(metadata.review_readiness_state || event.message.replace('Review readiness -> ', '').trim()),
      detail: metadata.review_readiness_reason || null
    }
  }
  if (event.type === 'completion_state_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Completion',
      value: completionStateLabel(metadata.completion_state || event.message.replace('Completion state -> ', '').trim()),
      detail: metadata.completion_reason || null
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
  if (event.type === 'repo_policy_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Repo policy',
      value: `${protectedBranchLabel(metadata.protected_branch_state)} · ${isolationStateLabel(metadata.isolation_state)}`,
      detail: metadata.protected_branch_reason || metadata.isolation_reason || null
    }
  }
  if (event.type === 'repo_baseline_changed') {
    return {
      id: event.id,
      timestamp: event.timestamp,
      label: 'Repo baseline',
      value: metadata.dirty_start_state || 'baseline updated',
      detail: metadata.changed_since_start_reason || metadata.dirty_start_reason || null
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

function missingValidationChecksText(rawValue) {
  const items = parseJsonList(rawValue)
  if (!items.length) return 'All expected recipe checks have been observed'
  return `Missing recipe checks: ${items.join(', ')}`
}

function validationPolicyLabel(state) {
  const map = {
    ready: 'Review-ready validation baseline',
    required_missing: 'Required validation checks missing',
    optional_pending: 'Optional validation checks pending',
    unknown: 'Validation policy not established'
  }
  return map[state] || 'Validation policy not established'
}

function reviewReadinessLabel(state) {
  const map = {
    ready: 'Review-ready',
    ready_with_gaps: 'Review-ready with optional gaps',
    not_ready: 'Not review-ready',
    unknown: 'Review readiness not established'
  }
  return map[state] || 'Review readiness not established'
}

function completionStateLabel(state) {
  const map = {
    in_progress: 'Still in progress',
    ready_for_review: 'Ready for review',
    ready_with_gaps: 'Ready for review with optional gaps',
    not_ready: 'Not ready for review',
    unknown: 'Completion state not established'
  }
  return map[state] || 'Completion state not established'
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
  if (session.review_readiness_state && session.review_readiness_state !== 'unknown') {
    parts.push(`review readiness is ${reviewReadinessLabel(session.review_readiness_state).toLowerCase()}`)
  }
  if (session.completion_state && session.completion_state !== 'unknown') {
    parts.push(`completion says ${completionStateLabel(session.completion_state).toLowerCase()}`)
  }
  if (session.changed_since_green_validation) {
    parts.push('code changed after the last green validation')
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
  const [validationPresets, setValidationPresets] = useState([])
  const [repoPolicies, setRepoPolicies] = useState([])
  const [selectedValidationPreset, setSelectedValidationPreset] = useState('')
  const [recipeDraft, setRecipeDraft] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [codexEnvironment, setCodexEnvironment] = useState(null)
  const [events, setEvents] = useState([])
  const [logs, setLogs] = useState([])
  const [validationHistory, setValidationHistory] = useState([])
  const [refresh, setRefresh] = useState(10)
  const [error, setError] = useState('')
  const [toast, setToast] = useState(null)
  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM)
  const [adoptForm, setAdoptForm] = useState(EMPTY_ADOPT_FORM)
  const [skillForm, setSkillForm] = useState(EMPTY_SKILL_FORM)
  const [codexConfigs, setCodexConfigs] = useState(EMPTY_CONFIG_EDITOR)
  const [activeConfigScope, setActiveConfigScope] = useState('global')
  const [codexRules, setCodexRules] = useState(EMPTY_RULES_EDITOR)
  const [activeRulesScope, setActiveRulesScope] = useState('workspace')
  const [codexAgents, setCodexAgents] = useState([])
  const [agentForm, setAgentForm] = useState(EMPTY_AGENT_FORM)
  const [activeAgentName, setActiveAgentName] = useState('')
  const [agentConfig, setAgentConfig] = useState(EMPTY_AGENT_CONFIG)
  const [codexMcp, setCodexMcp] = useState({ global: [], workspace: [] })
  const [mcpForm, setMcpForm] = useState(EMPTY_MCP_FORM)
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
  const matchedCreatePolicy = useMemo(
    () => matchRepoPolicyForPath(repoPolicies, createForm.repoPath),
    [createForm.repoPath, repoPolicies]
  )
  const matchedAdoptPolicy = useMemo(
    () => matchRepoPolicyForPath(repoPolicies, adoptForm.repoPath),
    [adoptForm.repoPath, repoPolicies]
  )
  const validationRecipe = parseValidationRecipe(detail?.validation_recipe_json || selectedSession?.validation_recipe_json)
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

  useEffect(() => {
    if (!validationPresets.length) {
      setSelectedValidationPreset('')
      return
    }
    setSelectedValidationPreset((current) => {
      if (current && validationPresets.some((preset) => preset.id === current)) {
        return current
      }
      return validationPresets[0].id
    })
  }, [validationPresets])

  useEffect(() => {
    setRecipeDraft(createRecipeDraft(validationRecipe))
  }, [detail?.validation_recipe_json, selectedSession?.validation_recipe_json])

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
      const [nextSummary, rows, presetPayload, repoPolicyPayload] = await Promise.all([
        fetchJson('/api/summary'),
        fetchJson('/api/sessions'),
        fetchJson('/api/validation-presets'),
        fetchJson('/api/repo-policies')
      ])
      startTransition(() => {
        setSummary(nextSummary)
        setSessions(rows)
        setValidationPresets(presetPayload.presets || [])
        setRepoPolicies(repoPolicyPayload.policies || [])
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
      setCodexEnvironment(null)
      setEvents([])
      setValidationHistory([])
      setLogs([])
      return
    }
    if (loadedDetailSessionRef.current !== id) {
      startTransition(() => {
        setDetail(null)
        setCodexEnvironment(null)
        setEvents([])
        setValidationHistory([])
        setLogs([])
      })
    }
    try {
      const [nextDetail, nextEvents, nextValidationHistory, nextLogs] = await Promise.all([
        fetchJson(`/api/sessions/${id}`),
        fetchJson(`/api/sessions/${id}/events?limit=25`),
        fetchJson(`/api/sessions/${id}/validation-history?limit=8`),
        fetchJson(`/api/sessions/${id}/logs?tail=120`)
      ])
      const nextCodexEnvironment = await fetchJson(
        `/api/codex-environment?repo_path=${encodeURIComponent((nextDetail.repo_path || '').trim())}`
      )
      if (detailRequestRef.current !== requestId) {
        return
      }
      loadedDetailSessionRef.current = id
      startTransition(() => {
        setDetail(nextDetail)
        setCodexEnvironment(nextCodexEnvironment)
        setEvents(nextEvents)
        setValidationHistory(nextValidationHistory)
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
    setValidationHistory([])
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

  function applyCreatePolicyDefaults() {
    if (!matchedCreatePolicy) return
    setCreateForm((prev) => ({
      ...prev,
      profile: matchedCreatePolicy.default_profile || prev.profile,
      createWorktreeForWrites: prev.createWorktreeForWrites || !!matchedCreatePolicy.require_worktree_for_write,
      requireChangelog: prev.requireChangelog || !!matchedCreatePolicy.require_changelog
    }))
    if (matchedCreatePolicy.require_worktree_for_write || matchedCreatePolicy.require_changelog) {
      setShowCreateAdvanced(true)
    }
    notify('success', `Applied repo policy defaults from ${matchedCreatePolicy.policy_id}`)
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

  async function createCodexSkill(event) {
    event.preventDefault()
    const payload = {
      scope: skillForm.scope,
      name: skillForm.name.trim(),
      summary: skillForm.summary.trim(),
      repoPath: skillForm.scope === 'workspace' ? (detail?.repo_path || selectedSession?.repo_path || '') : null
    }
    if (!payload.name) {
      notify('error', 'Skill name is required')
      return
    }
    if (payload.scope === 'workspace' && !payload.repoPath) {
      notify('error', 'Select a session with a working directory for workspace skills')
      return
    }
    const result = await runRequest(
      () =>
        fetchJson('/api/codex-skills', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }),
      (created) => `Created ${created.scope} skill ${created.name}`
    )
    if (!result) return
    setSkillForm((prev) => ({ ...EMPTY_SKILL_FORM, scope: prev.scope }))
    if (selectedSession?.id) {
      await loadDetail(selectedSession.id)
    }
  }

  async function loadCodexConfig(scope) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const payload = await runRequest(
      () => fetchJson(`/api/codex-config?scope=${encodeURIComponent(scope)}&repo_path=${encodeURIComponent(repoPath)}`),
      null
    )
    if (!payload) return
    setCodexConfigs((current) => ({
      ...current,
      [scope]: payload
    }))
  }

  async function saveCodexConfig(scope) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const config = codexConfigs[scope]
    if (!config) return
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope,
            content: config.content,
            repoPath: scope === 'workspace' ? repoPath : null
          })
        }),
      (result) => `Saved ${scope} Codex config at ${result.path}`
    )
    if (!payload) return
    await loadCodexConfig(scope)
    if (selectedSession?.id) {
      await loadDetail(selectedSession.id)
    }
  }

  async function restoreCodexConfig(scope, backupPath) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-config/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope,
            backupPath,
            repoPath: scope === 'workspace' ? repoPath : null
          })
        }),
      (result) => `Restored ${scope} Codex config from ${result.restoredFrom}`
    )
    if (!payload) return
    await loadCodexConfig(scope)
  }

  async function loadCodexRules(scope) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const payload = await runRequest(
      () => fetchJson(`/api/codex-rules?scope=${encodeURIComponent(scope)}&repo_path=${encodeURIComponent(repoPath)}`),
      null
    )
    if (!payload) return
    setCodexRules((current) => ({
      ...current,
      [scope]: payload
    }))
  }

  async function saveCodexRules(scope) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const rules = codexRules[scope]
    if (!rules) return
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-rules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope,
            content: rules.content,
            repoPath: scope === 'workspace' ? repoPath : null
          })
        }),
      (result) => `Saved ${scope} Codex rules at ${result.path}`
    )
    if (!payload) return
    await loadCodexRules(scope)
  }

  async function restoreCodexRules(scope, backupPath) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-rules/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope,
            backupPath,
            repoPath: scope === 'workspace' ? repoPath : null
          })
        }),
      (result) => `Restored ${scope} rules from ${result.restoredFrom}`
    )
    if (!payload) return
    await loadCodexRules(scope)
  }

  async function loadCodexAgents() {
    const payload = await runRequest(() => fetchJson('/api/codex-agents'), null)
    if (!payload) return
    setCodexAgents(payload.agents || [])
  }

  async function createCodexAgent(event) {
    event.preventDefault()
    const payload = {
      name: agentForm.name.trim(),
      summary: agentForm.summary.trim()
    }
    if (!payload.name) {
      notify('error', 'Agent name is required')
      return
    }
    const result = await runRequest(
      () =>
        fetchJson('/api/codex-agents', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }),
      (created) => `Created Codex agent ${created.name}`
    )
    if (!result) return
    setAgentForm(EMPTY_AGENT_FORM)
    await loadCodexAgents()
    await loadCodexConfig('global')
    await loadCodexAgentConfig(result.name)
    setActiveAgentName(result.name)
  }

  async function loadCodexAgentConfig(name) {
    if (!name) {
      setAgentConfig(EMPTY_AGENT_CONFIG)
      return
    }
    const payload = await runRequest(
      () => fetchJson(`/api/codex-agent-config?name=${encodeURIComponent(name)}`),
      null
    )
    if (!payload) return
    setAgentConfig(payload)
  }

  async function saveCodexAgentConfig() {
    if (!agentConfig.name) return
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-agent-config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: agentConfig.name,
            content: agentConfig.content
          })
        }),
      (saved) => `Saved agent config for ${saved.name}`
    )
    if (!payload) return
    await loadCodexAgentConfig(agentConfig.name)
  }

  async function restoreCodexAgentConfig(backupPath) {
    if (!agentConfig.name) return
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-agent-config/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: agentConfig.name,
            backupPath
          })
        }),
      (restored) => `Restored agent config for ${restored.name}`
    )
    if (!payload) return
    await loadCodexAgentConfig(agentConfig.name)
  }

  async function loadCodexMcp(scope) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const payload = await runRequest(
      () => fetchJson(`/api/codex-mcp?scope=${encodeURIComponent(scope)}&repo_path=${encodeURIComponent(repoPath)}`),
      null
    )
    if (!payload) return
    setCodexMcp((current) => ({ ...current, [scope]: payload.servers || [] }))
  }

  async function createCodexMcpServer(event) {
    event.preventDefault()
    const payload = {
      scope: mcpForm.scope,
      name: mcpForm.name.trim(),
      command: mcpForm.command.trim(),
      args: mcpForm.args.split(/\s+/).filter(Boolean),
      repoPath: mcpForm.scope === 'workspace' ? (detail?.repo_path || selectedSession?.repo_path || '') : null
    }
    if (!payload.name || !payload.command) {
      notify('error', 'MCP server name and command are required')
      return
    }
    if (payload.scope === 'workspace' && !payload.repoPath) {
      notify('error', 'Select a session with a working directory for workspace MCP entries')
      return
    }
    const result = await runRequest(
      () =>
        fetchJson('/api/codex-mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }),
      (created) => `Created ${created.scope} MCP server ${created.name}`
    )
    if (!result) return
    setMcpForm((prev) => ({ ...EMPTY_MCP_FORM, scope: prev.scope }))
    await loadCodexMcp(payload.scope)
    if (payload.scope === 'global') {
      await loadCodexConfig('global')
    } else {
      await loadCodexConfig('workspace')
    }
  }

  async function deleteCodexMcpServer(scope, name) {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const payload = await runRequest(
      () =>
        fetchJson('/api/codex-mcp/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scope,
            name,
            repoPath: scope === 'workspace' ? repoPath : null
          })
        }),
      (removed) => `Removed ${removed.scope} MCP server ${removed.name}`
    )
    if (!payload) return
    await loadCodexMcp(scope)
    if (scope === 'global') {
      await loadCodexConfig('global')
    } else {
      await loadCodexConfig('workspace')
    }
  }

  async function applyValidationPresetToSelected() {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    if (!repoPath || !selectedValidationPreset) {
      notify('error', 'Select a preset and a session with a working directory first')
      return
    }
    const payload = await runRequest(
      () =>
        fetchJson('/api/validation-presets/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            repoPath,
            presetId: selectedValidationPreset
          })
        }),
      (result) => `Applied preset ${selectedValidationPreset} at ${result.configPath}`
    )
    if (!payload) return
    await refreshAfterMutation(selectedSession?.id || null)
  }

  async function materializeValidationRecipeForSelected() {
    const repoPath = detail?.repo_path || selectedSession?.repo_path || ''
    const recipeJson = recipeDraft ? JSON.stringify(recipeDraft) : (detail?.validation_recipe_json || selectedSession?.validation_recipe_json || '')
    if (!repoPath || !recipeJson) {
      notify('error', 'Select a session with a working directory and detected validation recipe first')
      return
    }
    const payload = await runRequest(
      () =>
        fetchJson('/api/validation-recipes/materialize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            repoPath,
            recipeJson
          })
        }),
      (result) => `Saved local validation recipe at ${result.configPath}`
    )
    if (!payload) return
    await refreshAfterMutation(selectedSession?.id || null)
  }

  function resetRecipeDraft() {
    setRecipeDraft(createRecipeDraft(validationRecipe))
  }

  function updateRecipeDraftLabel(value) {
    setRecipeDraft((current) => (current ? { ...current, label: value } : current))
  }

  function updateRecipeDraftCheck(index, key, value) {
    setRecipeDraft((current) => {
      if (!current) return current
      return {
        ...current,
        checks: current.checks.map((check, checkIndex) => (
          checkIndex === index ? { ...check, [key]: value } : check
        ))
      }
    })
  }

  const activeCount = sessions.filter((session) => !isArchivedSession(session)).length
  const archivedCount = sessions.filter((session) => isArchivedSession(session)).length

  useEffect(() => {
    if (commandTab !== 'environment' || !showCommandPanel) return
    loadCodexConfig('global')
    if (detail?.repo_path || selectedSession?.repo_path) {
      loadCodexConfig('workspace')
    } else {
      setCodexConfigs((current) => ({ ...current, workspace: null }))
    }
    loadCodexRules('global')
    if (detail?.repo_path || selectedSession?.repo_path) {
      loadCodexRules('workspace')
    } else {
      setCodexRules((current) => ({ ...current, workspace: null }))
    }
    loadCodexAgents()
    loadCodexMcp('global')
    if (detail?.repo_path || selectedSession?.repo_path) {
      loadCodexMcp('workspace')
    } else {
      setCodexMcp((current) => ({ ...current, workspace: [] }))
    }
  }, [commandTab, detail?.repo_path, selectedSession?.repo_path, showCommandPanel])

  useEffect(() => {
    if (commandTab !== 'environment' || !showCommandPanel) return
    if (!codexAgents.length) {
      setActiveAgentName('')
      setAgentConfig(EMPTY_AGENT_CONFIG)
      return
    }
    const nextName = codexAgents.some((agent) => agent.name === activeAgentName) ? activeAgentName : codexAgents[0].name
    if (nextName !== activeAgentName) {
      setActiveAgentName(nextName)
    }
    loadCodexAgentConfig(nextName)
  }, [activeAgentName, codexAgents, commandTab, showCommandPanel])

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
              <h2>{
                commandTab === 'create'
                  ? 'Create and manage sessions'
                  : commandTab === 'adopt'
                    ? 'Adopt existing Codex work'
                    : commandTab === 'environment'
                      ? 'Inspect and shape Codex environment assets'
                      : 'Review and clean archived sessions'
              }</h2>
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
                    {matchedCreatePolicy ? (
                      <div className="policy-hint">
                        <p><strong>Matched repo policy:</strong> {matchedCreatePolicy.label}</p>
                        <p className="muted">
                          {matchedCreatePolicy.require_worktree_for_write ? 'Requires dedicated worktree for writable sessions. ' : ''}
                          {matchedCreatePolicy.require_changelog ? 'Requires CHANGELOG entry. ' : ''}
                          {matchedCreatePolicy.default_profile ? `Suggested profile: ${matchedCreatePolicy.default_profile}. ` : ''}
                          {matchedCreatePolicy.default_approval_policy ? `Default approval: ${matchedCreatePolicy.default_approval_policy}.` : ''}
                        </p>
                        <button type="button" className="ghost" onClick={applyCreatePolicyDefaults}>Apply policy defaults</button>
                      </div>
                    ) : null}
                    {validationPresets.length ? (
                      <p className="muted">Manager validation presets: {validationPresets.map((preset) => preset.id).join(', ')}</p>
                    ) : null}
                    {repoPolicies.length ? (
                      <p className="muted">Manager repo policies: {repoPolicies.map((policy) => policy.policy_id).join(', ')}</p>
                    ) : null}
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
                    {matchedAdoptPolicy ? (
                      <div className="policy-hint">
                        <p><strong>Matched repo policy:</strong> {matchedAdoptPolicy.label}</p>
                        <p className="muted">
                          {matchedAdoptPolicy.require_worktree_for_write ? 'Writable resumes in this repo are expected to use worktree isolation. ' : ''}
                          {matchedAdoptPolicy.require_changelog ? 'This repo expects a CHANGELOG entry for tracked work. ' : ''}
                          {matchedAdoptPolicy.default_profile ? `Suggested profile: ${matchedAdoptPolicy.default_profile}. ` : ''}
                          {matchedAdoptPolicy.default_approval_policy ? `Default approval: ${matchedAdoptPolicy.default_approval_policy}.` : ''}
                        </p>
                      </div>
                    ) : null}
                    {validationPresets.length ? (
                      <p className="muted">Available manager presets: {validationPresets.map((preset) => preset.id).join(', ')}</p>
                    ) : null}
                    {repoPolicies.length ? (
                      <p className="muted">Available manager repo policies: {repoPolicies.map((policy) => policy.policy_id).join(', ')}</p>
                    ) : null}
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
              <div className="history-browser">
                <div className="row between history-browser-head">
                  <div>
                    <p className="eyebrow">MCP Servers</p>
                    <p className="muted">Inspect configured MCP servers and register new entries in Codex config.</p>
                  </div>
                  <span className="badge badge-stopped">{`${codexMcp.global.length} global · ${codexMcp.workspace.length} workspace`}</span>
                </div>
                <div className="history-list">
                  {[...codexMcp.global.map((server) => ({ ...server, scope: 'global' })), ...codexMcp.workspace.map((server) => ({ ...server, scope: 'workspace' }))].map((server) => (
                    <div key={`${server.scope}-${server.name}`} className="history-item">
                      <div className="row between">
                        <strong>{server.name}</strong>
                        <div className="row gap-sm">
                          <span className="badge badge-stopped">{server.scope}</span>
                          <button className="ghost danger-text" type="button" onClick={() => deleteCodexMcpServer(server.scope, server.name)}>
                            Remove
                          </button>
                        </div>
                      </div>
                      <p className="muted">{server.command}{server.args?.length ? ` ${server.args.join(' ')}` : ''}</p>
                    </div>
                  ))}
                  {!codexMcp.global.length && !codexMcp.workspace.length ? <p className="muted">No MCP servers configured yet.</p> : null}
                </div>
                <form className="stack-form" onSubmit={createCodexMcpServer}>
                  <div className="command-settings-grid adopt-settings-grid">
                    <label className="field">
                      <span>MCP scope</span>
                      <select value={mcpForm.scope} onChange={(event) => setMcpForm((prev) => ({ ...prev, scope: event.target.value }))}>
                        <option value="global">global</option>
                        <option value="workspace">workspace</option>
                      </select>
                    </label>
                    <div className="helper-copy">
                      <span className="field-label">What gets written</span>
                      <p className="muted">Adds a new `[mcp_servers.\"name\"]` entry to the selected Codex config.</p>
                    </div>
                  </div>
                  <div className="command-form-grid">
                    <input placeholder="Server name" value={mcpForm.name} onChange={(event) => setMcpForm((prev) => ({ ...prev, name: event.target.value }))} />
                    <input placeholder="Command" value={mcpForm.command} onChange={(event) => setMcpForm((prev) => ({ ...prev, command: event.target.value }))} />
                  </div>
                  <input placeholder="Args (space-separated)" value={mcpForm.args} onChange={(event) => setMcpForm((prev) => ({ ...prev, args: event.target.value }))} />
                  <button type="submit" className="primary">Add MCP server</button>
                </form>
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

          {showCommandPanel && commandTab === 'environment' ? (
            <div className="command-pane">
              <div className="command-head">
                <div>
                  <p className="eyebrow">Codex Environment</p>
                  <h2>Configs and skills</h2>
                </div>
                <span className="badge badge-stopped">{detail?.repo_path || selectedSession?.repo_path ? 'session-scoped' : 'global-only'}</span>
              </div>
              <div className="history-browser">
                <div className="history-item">
                  <div className="row between">
                    <strong>Config inventory</strong>
                    <span className="badge badge-stopped">{codexEnvironment?.codexHome || 'no Codex home'}</span>
                  </div>
                  <p className="muted">Global config: {codexEnvironment?.globalConfig?.exists ? codexEnvironment.globalConfig.path : 'missing'}</p>
                  <p className="muted">Workspace config: {codexEnvironment?.workspaceConfig?.exists ? codexEnvironment.workspaceConfig.path : 'missing'}</p>
                </div>
                <div className="history-item">
                  <div className="row between">
                    <strong>Installed skills</strong>
                    <span className="badge badge-running">
                      {`${codexEnvironment?.globalSkills?.length || 0} global · ${codexEnvironment?.workspaceSkills?.length || 0} workspace`}
                    </span>
                  </div>
                  <p className="muted">
                    Global: {(codexEnvironment?.globalSkills || []).map((skill) => skill.name).join(', ') || 'none'}
                  </p>
                  <p className="muted">
                    Workspace: {(codexEnvironment?.workspaceSkills || []).map((skill) => skill.name).join(', ') || 'none'}
                  </p>
                </div>
              </div>
              <form className="stack-form" onSubmit={createCodexSkill}>
                <div className="command-settings-grid adopt-settings-grid">
                  <label className="field">
                    <span>Skill scope</span>
                    <select value={skillForm.scope} onChange={(event) => setSkillForm((prev) => ({ ...prev, scope: event.target.value }))}>
                      <option value="global">global</option>
                      <option value="workspace">workspace</option>
                    </select>
                  </label>
                  <div className="helper-copy">
                    <span className="field-label">Creation target</span>
                    <p className="muted">
                      {skillForm.scope === 'workspace'
                        ? `Workspace skills are created under ${(detail?.repo_path || selectedSession?.repo_path || 'the selected repo')}/.codex/skills`
                        : `Global skills are created under ${codexEnvironment?.codexHome || '~/.codex'}/skills`}
                    </p>
                  </div>
                </div>
                <div className="command-form-grid">
                  <input placeholder="Skill name (e.g. release-guard)" value={skillForm.name} onChange={(event) => setSkillForm((prev) => ({ ...prev, name: event.target.value }))} />
                  <input placeholder="Short purpose summary" value={skillForm.summary} onChange={(event) => setSkillForm((prev) => ({ ...prev, summary: event.target.value }))} />
                </div>
                <button type="submit" className="primary">Create skill scaffold</button>
              </form>
              <div className="history-browser">
                <div className="row between history-browser-head">
                  <div>
                    <p className="eyebrow">Codex Config Editor</p>
                    <p className="muted">Read and update Codex config on the execution host with a simple backup on save.</p>
                  </div>
                  <div className="row">
                    <button type="button" className={`ghost ${activeConfigScope === 'global' ? 'active-filter' : ''}`} onClick={() => setActiveConfigScope('global')}>Global</button>
                    <button type="button" className={`ghost ${activeConfigScope === 'workspace' ? 'active-filter' : ''}`} onClick={() => setActiveConfigScope('workspace')} disabled={!(detail?.repo_path || selectedSession?.repo_path)}>Workspace</button>
                  </div>
                </div>
                {codexConfigs[activeConfigScope] ? (
                  <div className="stack-form">
                    <p className="muted">
                      {codexConfigs[activeConfigScope].exists
                        ? `Editing ${codexConfigs[activeConfigScope].path}`
                        : `No config exists yet. Saving will create ${codexConfigs[activeConfigScope].path}`}
                    </p>
                    <textarea
                      rows="10"
                      value={codexConfigs[activeConfigScope].content}
                      onChange={(event) => setCodexConfigs((current) => ({
                        ...current,
                        [activeConfigScope]: {
                          ...current[activeConfigScope],
                          content: event.target.value
                        }
                      }))}
                    />
                    <button type="button" className="primary" onClick={() => saveCodexConfig(activeConfigScope)}>Save Codex config</button>
                    {codexConfigs[activeConfigScope].backups?.length ? (
                      <div className="history-list">
                        {codexConfigs[activeConfigScope].backups.slice(0, 5).map((backup) => (
                          <div key={backup.path} className="history-item">
                            <div className="row between">
                              <strong>{backup.name}</strong>
                              <span className="badge badge-stopped">{formatEventTime(backup.modifiedAt)}</span>
                            </div>
                            <button type="button" className="ghost" onClick={() => restoreCodexConfig(activeConfigScope, backup.path)}>Restore this backup</button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">Load a global or workspace config to edit it here.</p>
                )}
              </div>
              <div className="history-browser">
                <div className="row between history-browser-head">
                  <div>
                    <p className="eyebrow">Instruction Rules</p>
                    <p className="muted">Edit global or repo-level AGENTS.md guidance on the execution host.</p>
                  </div>
                  <div className="row">
                    <button type="button" className={`ghost ${activeRulesScope === 'global' ? 'active-filter' : ''}`} onClick={() => setActiveRulesScope('global')}>Global</button>
                    <button type="button" className={`ghost ${activeRulesScope === 'workspace' ? 'active-filter' : ''}`} onClick={() => setActiveRulesScope('workspace')} disabled={!(detail?.repo_path || selectedSession?.repo_path)}>Workspace</button>
                  </div>
                </div>
                {codexRules[activeRulesScope] ? (
                  <div className="stack-form">
                    <p className="muted">
                      {codexRules[activeRulesScope].exists
                        ? `Editing ${codexRules[activeRulesScope].path}`
                        : `No rules file exists yet. Saving will create ${codexRules[activeRulesScope].path}`}
                    </p>
                    <textarea
                      rows="10"
                      value={codexRules[activeRulesScope].content}
                      onChange={(event) => setCodexRules((current) => ({
                        ...current,
                        [activeRulesScope]: {
                          ...current[activeRulesScope],
                          content: event.target.value
                        }
                      }))}
                    />
                    <button type="button" className="primary" onClick={() => saveCodexRules(activeRulesScope)}>Save rules</button>
                    {codexRules[activeRulesScope].backups?.length ? (
                      <div className="history-list">
                        {codexRules[activeRulesScope].backups.slice(0, 5).map((backup) => (
                          <div key={backup.path} className="history-item">
                            <div className="row between">
                              <strong>{backup.name}</strong>
                              <span className="badge badge-stopped">{formatEventTime(backup.modifiedAt)}</span>
                            </div>
                            <button type="button" className="ghost" onClick={() => restoreCodexRules(activeRulesScope, backup.path)}>Restore this backup</button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <p className="muted">Load a global or workspace rules file to edit it here.</p>
                )}
              </div>
              <div className="history-browser">
                <div className="row between history-browser-head">
                  <div>
                    <p className="eyebrow">Configured Agents</p>
                    <p className="muted">Inspect, scaffold, and edit named Codex agents registered in global config.</p>
                  </div>
                  <span className="badge badge-stopped">{codexAgents.length} configured</span>
                </div>
                <div className="history-list">
                  {codexAgents.length ? codexAgents.map((agent) => (
                    <div key={agent.name} className="history-item">
                      <div className="row between">
                        <strong>{agent.name}</strong>
                        <span className="badge badge-stopped">{agent.configFile || 'no config file'}</span>
                      </div>
                      <button type="button" className="ghost" onClick={() => setActiveAgentName(agent.name)}>Edit config</button>
                    </div>
                  )) : <p className="muted">No configured agents yet.</p>}
                </div>
                <form className="stack-form" onSubmit={createCodexAgent}>
                  <div className="command-form-grid">
                    <input placeholder="Agent name (e.g. release-captain)" value={agentForm.name} onChange={(event) => setAgentForm((prev) => ({ ...prev, name: event.target.value }))} />
                    <input placeholder="Short role summary" value={agentForm.summary} onChange={(event) => setAgentForm((prev) => ({ ...prev, summary: event.target.value }))} />
                  </div>
                  <button type="submit" className="primary">Create agent scaffold</button>
                </form>
                {activeAgentName ? (
                  <div className="stack-form">
                    <div className="row between history-browser-head">
                      <div>
                        <p className="eyebrow">Agent Config Editor</p>
                        <p className="muted">
                          {agentConfig.exists
                            ? `Editing ${agentConfig.path}`
                            : `No agent config exists yet. Saving will create ${agentConfig.path}`}
                        </p>
                      </div>
                      <span className="badge badge-running">{activeAgentName}</span>
                    </div>
                    <textarea
                      rows="10"
                      value={agentConfig.content}
                      onChange={(event) => setAgentConfig((current) => ({
                        ...current,
                        content: event.target.value
                      }))}
                    />
                    <button type="button" className="primary" onClick={() => saveCodexAgentConfig()}>Save agent config</button>
                    {agentConfig.backups?.length ? (
                      <div className="history-list">
                        {agentConfig.backups.slice(0, 5).map((backup) => (
                          <div key={backup.path} className="history-item">
                            <div className="row between">
                              <strong>{backup.name}</strong>
                              <span className="badge badge-stopped">{formatEventTime(backup.modifiedAt)}</span>
                            </div>
                            <button type="button" className="ghost" onClick={() => restoreCodexAgentConfig(backup.path)}>Restore this backup</button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
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
                  <span className="overview-label">Codex config</span>
                  <span className="overview-value">
                    global {codexEnvironment?.globalConfig?.exists ? 'present' : 'missing'}
                    {' · '}
                    workspace {codexEnvironment?.workspaceConfig?.exists ? 'present' : 'missing'}
                  </span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Skill inventory</span>
                  <span className="overview-value">
                    global {codexEnvironment?.globalSkills?.length || 0}
                    {' · '}
                    workspace {codexEnvironment?.workspaceSkills?.length || 0}
                  </span>
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
                <div className="overview-item">
                  <span className="overview-label">Protected branch</span>
                  <span className="overview-value">{protectedBranchLabel(detail?.protected_branch_state || selectedSession.protected_branch_state)}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Isolation policy</span>
                  <span className="overview-value">{isolationStateLabel(detail?.isolation_state || selectedSession.isolation_state)}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Repo policy</span>
                  <span className="overview-value">{detail?.repo_policy_label || selectedSession.repo_policy_label || 'none'}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Start baseline</span>
                  <span className="overview-value">{detail?.dirty_start_state || selectedSession.dirty_start_state || 'clean'}</span>
                </div>
                <div className="overview-item">
                  <span className="overview-label">Drift since start</span>
                  <span className="overview-value">{(detail?.changed_since_start ?? selectedSession.changed_since_start) ? 'changed' : 'matches start'}</span>
                </div>
                {(detail?.protected_branch_reason || selectedSession.protected_branch_reason) ? (
                  <div className="overview-item overview-item-wide">
                    <span className="overview-label">Protected branch reason</span>
                    <span className="overview-value">{detail?.protected_branch_reason || selectedSession.protected_branch_reason}</span>
                  </div>
                ) : null}
                {(detail?.isolation_reason || selectedSession.isolation_reason) ? (
                  <div className="overview-item overview-item-wide">
                    <span className="overview-label">Isolation reason</span>
                    <span className="overview-value">{detail?.isolation_reason || selectedSession.isolation_reason}</span>
                  </div>
                ) : null}
                {(detail?.repo_policy_id || selectedSession.repo_policy_id) ? (
                  <div className="overview-item overview-item-wide">
                    <span className="overview-label">Policy id</span>
                    <span className="overview-value">{detail?.repo_policy_id || selectedSession.repo_policy_id}</span>
                  </div>
                ) : null}
                {(detail?.dirty_start_reason || selectedSession.dirty_start_reason) ? (
                  <div className="overview-item overview-item-wide">
                    <span className="overview-label">Start baseline reason</span>
                    <span className="overview-value">{detail?.dirty_start_reason || selectedSession.dirty_start_reason}</span>
                  </div>
                ) : null}
                {(detail?.changed_since_start_reason || selectedSession.changed_since_start_reason) ? (
                  <div className="overview-item overview-item-wide">
                    <span className="overview-label">Drift reason</span>
                    <span className="overview-value">{detail?.changed_since_start_reason || selectedSession.changed_since_start_reason}</span>
                  </div>
                ) : null}
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
            {validationRecipe?.label ? (
              <>
                <p className="muted">Validation recipe: {validationRecipe.label}</p>
                <p className="muted">Recipe source: {validationRecipeSourceLabel(detail?.validation_recipe_id || selectedSession?.validation_recipe_id || null)}</p>
                {validationPresets.length ? (
                  <div className="activity-subsection">
                    <p className="activity-label">Manager presets</p>
                    <div className="row">
                      <select value={selectedValidationPreset} onChange={(event) => setSelectedValidationPreset(event.target.value)}>
                        {validationPresets.map((preset) => (
                          <option key={preset.id} value={preset.id}>{preset.id}</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="ghost"
                        onClick={applyValidationPresetToSelected}
                        disabled={!selectedSession?.repo_path || !selectedValidationPreset}
                      >
                        Apply preset reference
                      </button>
                      <button
                        type="button"
                        className="ghost"
                        onClick={materializeValidationRecipeForSelected}
                        disabled={!selectedSession?.repo_path}
                      >
                        Save local recipe
                      </button>
                    </div>
                  </div>
                ) : null}
                {Array.isArray(validationRecipe.checks) && validationRecipe.checks.length ? (
                  <div className="activity-subsection">
                    <div className="row">
                      <p className="activity-label">Local recipe</p>
                      <div className="row">
                        <button
                          type="button"
                          className="ghost"
                          onClick={resetRecipeDraft}
                          disabled={!recipeDraft}
                        >
                          Reset draft
                        </button>
                        <button
                          type="button"
                          className="ghost"
                          onClick={materializeValidationRecipeForSelected}
                          disabled={!selectedSession?.repo_path || !recipeDraft}
                        >
                          Save local recipe
                        </button>
                      </div>
                    </div>
                    {recipeDraft ? (
                      <div className="recipe-draft">
                        <label className="field">
                          <span className="muted">Recipe label</span>
                          <input
                            type="text"
                            value={recipeDraft.label}
                            onChange={(event) => updateRecipeDraftLabel(event.target.value)}
                          />
                        </label>
                        {recipeDraft.checks.map((check, index) => (
                          <div key={`${check.kind}-${index}`} className="recipe-draft-check">
                            <div className="row between">
                              <strong>{phaseLabel(check.kind)}</strong>
                              <label className="checkbox muted">
                                <input
                                  type="checkbox"
                                  checked={check.required !== false}
                                  onChange={(event) => updateRecipeDraftCheck(index, 'required', event.target.checked)}
                                />
                                Required
                              </label>
                            </div>
                            <label className="field">
                              <span className="muted">Check label</span>
                              <input
                                type="text"
                                value={check.label}
                                onChange={(event) => updateRecipeDraftCheck(index, 'label', event.target.value)}
                              />
                            </label>
                            <label className="field">
                              <span className="muted">Command</span>
                              <input
                                type="text"
                                value={check.command}
                                onChange={(event) => updateRecipeDraftCheck(index, 'command', event.target.value)}
                              />
                            </label>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {Array.isArray(validationRecipe.checks) && validationRecipe.checks.length ? (
                  <div className="activity-subsection">
                    <p className="activity-label">Expected checks</p>
                    {validationRecipe.checks.map((check, index) => (
                      <div key={`${check.kind}-${check.command}-${index}`} className="phase-timeline-item validation-history-item">
                        <div className="phase-timeline-text">
                          <div className="phase-timeline-main">
                            <strong>{check.label || phaseLabel(check.kind)}</strong>
                            <span className="muted">
                              {validationCheckRequirementLabel(check.required)} · {validationCheckObservedState(check.kind, detail || selectedSession || {})}
                            </span>
                          </div>
                          <p className="muted timeline-detail">{check.command}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <p className="muted">Validation recipe: not detected yet</p>
                {validationPresets.length ? (
                  <div className="activity-subsection">
                    <p className="activity-label">Manager presets</p>
                    <div className="row">
                      <select value={selectedValidationPreset} onChange={(event) => setSelectedValidationPreset(event.target.value)}>
                        {validationPresets.map((preset) => (
                          <option key={preset.id} value={preset.id}>{preset.id}</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="ghost"
                        onClick={applyValidationPresetToSelected}
                        disabled={!selectedSession?.repo_path || !selectedValidationPreset}
                      >
                        Apply preset reference
                      </button>
                      <button
                        type="button"
                        className="ghost"
                        onClick={materializeValidationRecipeForSelected}
                        disabled={!selectedSession?.repo_path}
                      >
                        Save local recipe
                      </button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
            <p className="muted">{validationActivityLabel('tests', detail?.test_activity || 'none')}</p>
            <p className="muted">{validationResultDetail('tests', detail?.test_status || 'unknown', detail?.test_status_at)}</p>
            <p className="muted">{validationActivityLabel('lint', detail?.lint_activity || 'none')}</p>
            <p className="muted">{validationResultDetail('lint', detail?.lint_status || 'unknown', detail?.lint_status_at)}</p>
            <p className="muted">{validationActivityLabel('build', detail?.build_activity || 'none')}</p>
            <p className="muted">{validationResultDetail('build', detail?.build_status || 'unknown', detail?.build_status_at)}</p>
            <p className="muted">{latestGreenValidationLabel(detail || selectedSession)}</p>
            <p className="muted">
              {(detail?.changed_since_green_validation || selectedSession?.changed_since_green_validation)
                ? (detail?.changed_since_green_reason || selectedSession?.changed_since_green_reason || 'Code changed since the last green validation')
                : 'Repo still matches the last green validation snapshot'}
            </p>
            <p className="muted">
              {validationPolicyLabel(detail?.validation_policy_state || selectedSession?.validation_policy_state || 'unknown')}
            </p>
            <p className="muted">
              {detail?.validation_policy_reason || selectedSession?.validation_policy_reason || detail?.validation_coverage_reason || selectedSession?.validation_coverage_reason || missingValidationChecksText(detail?.missing_validation_checks_json || selectedSession?.missing_validation_checks_json)}
            </p>
            <p className="muted">
              {reviewReadinessLabel(detail?.review_readiness_state || selectedSession?.review_readiness_state || 'unknown')}
            </p>
            <p className="muted">
              {detail?.review_readiness_reason || selectedSession?.review_readiness_reason || 'Review readiness has not been established yet'}
            </p>
            <p className="muted">
              {completionStateLabel(detail?.completion_state || selectedSession?.completion_state || 'unknown')}
            </p>
            <p className="muted">
              {detail?.completion_reason || selectedSession?.completion_reason || 'Completion state has not been established yet'}
            </p>
            <div className="activity-subsection">
              <p className="activity-label">Recent validation runs</p>
              {!validationHistory.length ? <p className="muted">No structured validation history recorded yet.</p> : null}
              {validationHistory.slice(0, 5).map((entry) => (
                <div key={entry.id} className="phase-timeline-item validation-history-item">
                  <div className="phase-timeline-text">
                    <div className="phase-timeline-main">
                      <strong>{validationHistoryEntryLabel(entry)}</strong>
                      <span className="muted">
                        {entry.kind}
                        {entry.activity ? ` · activity ${entry.activity}` : ''}
                        {entry.status ? ` · status ${entry.status}` : ''}
                      </span>
                    </div>
                  </div>
                  <span className="muted">{formatEventTime(entry.timestamp)}</span>
                </div>
              ))}
            </div>
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

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
    return kind === 'tests' ? 'no test detected' : 'no lint detected'
  }
  return `${kind} ${status}`
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
  const [fastPollUntil, setFastPollUntil] = useState(0)
  const logOutputRef = useRef(null)
  const stickLogToBottomRef = useRef(true)
  const previousSelectedIdRef = useRef(null)
  const fastPollSessionIdRef = useRef(null)
  const fastPollExtendedRef = useRef(false)
  const previousLogSignatureRef = useRef('')

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
        session.branch
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery))
    })
  }, [normalizedQuery, sessions, showArchive])

  const selectedSession = useMemo(
    () => visibleSessions.find((session) => session.id === selectedId) || sessions.find((session) => session.id === selectedId) || null,
    [selectedId, sessions, visibleSessions]
  )
  const canAct = !!selectedSession
  const pollIntervalSeconds = Date.now() < fastPollUntil ? 2 : refresh

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
    if (!id) {
      setDetail(null)
      setEvents([])
      setLogs([])
      return
    }
    try {
      const [nextDetail, nextEvents, nextLogs] = await Promise.all([
        fetchJson(`/api/sessions/${id}`),
        fetchJson(`/api/sessions/${id}/events?limit=25`),
        fetchJson(`/api/sessions/${id}/logs?tail=120`)
      ])
      startTransition(() => {
        setDetail(nextDetail)
        setEvents(nextEvents)
        setLogs(trimTrailingBlankLines((nextLogs.lines || []).map(sanitizeLogLine)))
      })
    } catch (err) {
      const message = formatError(err)
      if (message.toLowerCase().includes('session not found')) {
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
        () => `Resume command ready for ${selectedSession.name}`
      )
      if (!payload) return
      await copyOrNotify(payload.command, 'Resume attach command copied to clipboard')
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
    if (!payload.repoPath) {
      notify('error', 'Repo path is required')
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
          </div>

          {commandTab === 'create' ? (
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
                  <input placeholder="Repo path (absolute)" value={createForm.repoPath} onChange={(event) => onCreateField('repoPath', event.target.value)} />
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
                    <p className="muted">This controls Codex permissions and approval behavior. It does not provide a task prompt by itself.</p>
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

          {commandTab === 'adopt' ? (
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
            </div>
          ) : null}

          {commandTab === 'cleanup' ? (
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

      <section className="cards">
        <article className="card">
          <h3>Focus</h3>
          <p>{selectedSession?.name || 'No session selected'}</p>
          {selectedSession ? (
            <>
              <p className={badgeClass(selectedSession.status)}>{selectedSession.status}</p>
              <p className="muted">{selectedSession.repo_path}</p>
              <p className="muted">{selectedSession.mode} · {selectedSession.profile}</p>
            </>
          ) : null}
        </article>

        <article className="card">
          <h3>Activity</h3>
          <p>{detail?.last_known_activity || 'No activity yet'}</p>
          <p className="muted">Updated {detail?.updated_at || '-'}</p>
          <p className="muted">Output lines: {logs.length}</p>
          <div className="row validation-row">
            <span className={validationBadgeClass(detail?.test_status || 'unknown')}>{validationLabel('tests', detail?.test_status || 'unknown')}</span>
            <span className={validationBadgeClass(detail?.lint_status || 'unknown')}>{validationLabel('lint', detail?.lint_status || 'unknown')}</span>
          </div>
        </article>

        <article className="card">
          <h3>Repo State</h3>
          <p>Branch: {detail?.branch || '(default)'}</p>
          <p>Changed files: {detail?.changed_files_count ?? 0}</p>
          <p className="muted">{detail?.worktree_path || detail?.repo_path || '-'}</p>
        </article>

        <article className="card">
          <h3>Execution</h3>
          <p>Permissions: {detail?.profile || '-'}</p>
          <p>Approval: {detail?.approval_policy || '-'}</p>
          <p className="muted">tmux: {detail?.tmux_session || '-'}</p>
          <p className="muted">Attachment: {detail?.attachment_state || 'detached'}</p>
          <p className="muted">CHANGELOG discipline: {detail?.require_changelog ? 'required' : 'optional'}</p>
          <div className="actions">
            <button disabled={!canAct} onClick={() => runAction('attach')}>Copy Attach Command</button>
            <button disabled={!canAct} onClick={() => runAction('resume')}>Resume</button>
            <button disabled={!canAct} className="danger" onClick={() => runAction('stop')}>Stop</button>
            <button disabled={!canAct} className="danger" onClick={() => runAction('delete')}>Delete</button>
          </div>
        </article>
      </section>

      <section className="main-grid">
        <article className="panel">
          <div className="panel-head">
            <div>
              <h2>Session Grid</h2>
              <p className="muted">Filter current and archived sessions without losing selection context.</p>
            </div>
            <input
              className="filter-input"
              placeholder="Filter by name, branch, profile..."
              value={sessionQuery}
              onChange={(event) => setSessionQuery(event.target.value)}
            />
          </div>
          <div className="grid-list">
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
                <p className="muted">{validationLabel('tests', session.test_status || 'unknown')} · {validationLabel('lint', session.lint_status || 'unknown')}</p>
                <p className="muted">{session.last_known_activity || '-'}</p>
              </button>
            ))}
          </div>
        </article>

        <article className="panel">
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
          <h2>Recent Events</h2>
          <div className="events">
            {events.map((event) => (
              <div key={event.id} className="event-item">
                <span>{event.timestamp}</span>
                <strong>{event.type}</strong>
                <p>{event.message}</p>
              </div>
            ))}
          </div>
        </article>

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

import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import ProjectSettingsDialog from '../components/ProjectSettingsDialog'
import PluginIngestDialog from '../components/PluginIngestDialog'
import WorkDetailModal from '../components/WorkDetailModal'
import RatedChunksModal from '../components/RatedChunksModal'
import { useIsMobile } from '../hooks/useIsMobile'
import type { AIRatingStatus, BatchIngestEvent, PipelineStreamEvent, PluginIngestEvent, UpdatePluginEvent } from '../api/types'

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

/** Returns formatted token string if total > 0, empty string otherwise. Handles undefined fields. */
function tokenLabel(prompt: number | undefined, completion: number | undefined): string {
  const total = (prompt ?? 0) + (completion ?? 0)
  return total > 0 ? fmtTokens(total) : ''
}

type PhaseStatus = 'waiting' | 'running' | 'done' | 'error'
type PhaseProgress = { phase: string; status: PhaseStatus; items?: number; current?: number; total?: number }

const PHASES = ['chunk', 'embed', 'cluster']

const PHASE_LABELS: Record<string, string> = {
  chunk: 'Chunking',
  embed: 'Embedding',
  cluster: 'Processing',
}

const PIPELINE_PHASE_DISPLAY: Record<string, string> = {
  ingested: 'ingested',
  chunked: 'chunked',
  embedded: 'embedded',
  clustered: 'processed',
}

function thermalColor(v: number): string {
  if (v >= 4.5) return '#f97316'  // orange — hot
  if (v >= 3.5) return '#fbbf24'  // amber — warm
  if (v >= 2.5) return '#94a3b8'  // slate — neutral
  if (v >= 1.5) return '#7dd3fc'  // sky — cool
  return '#818cf8'                // indigo — cold
}

function PipelineProgress({ phases, error }: { phases: PhaseProgress[]; error?: string }) {
  return (
    <div style={{ marginTop: 8, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {phases.map(p => (
        <div key={p.phase} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ width: 14, textAlign: 'center', color: p.status === 'done' ? '#2e7d32' : p.status === 'error' ? '#c00' : p.status === 'running' ? '#6b7de0' : '#bbb' }}>
            {p.status === 'done' ? '✓' : p.status === 'error' ? '✗' : p.status === 'running' ? '…' : '·'}
          </span>
          <span style={{ color: p.status === 'waiting' ? 'var(--text-muted)' : 'inherit', minWidth: 90 }}>
            {PHASE_LABELS[p.phase] ?? p.phase}
          </span>
          {p.status === 'running' && (
            <span style={{ color: 'var(--text-muted)' }}>
              {p.current != null && p.total != null
                ? `${p.current} of ${p.total}`
                : p.total != null
                ? `${p.total} items`
                : '…'}
            </span>
          )}
          {p.status === 'done' && p.items !== undefined && (
            <span style={{ color: 'var(--text-muted)' }}>{p.items} item{p.items !== 1 ? 's' : ''}</span>
          )}
        </div>
      ))}
      {error && <p style={{ margin: '4px 0 0', color: '#c00' }}>{error}</p>}
    </div>
  )
}

export default function ProjectDashboard() {
  const { projectId } = useParams<{ projectId: string }>()!
  const qc = useQueryClient()
  const [showSettings, setShowSettings] = useState(false)
  const [showPluginIngest, setShowPluginIngest] = useState(false)
  const [detailWorkRef, setDetailWorkRef] = useState<string | number | null>(null)
  const [ratedChunksFilter, setRatedChunksFilter] = useState<{ workSeq?: number; title?: string } | null>(null)

  // Update state
  const [updateRunning, setUpdateRunning] = useState(false)
  const [updateLog, setUpdateLog] = useState<Array<{ work: string; status: string }>>([])
  const [updateCounts, setUpdateCounts] = useState<{ updated: number; unchanged: number } | null>(null)
  const [updatePhase, setUpdatePhase] = useState<'checking' | 'fetching' | null>(null)
  const [updateFetchTotal, setUpdateFetchTotal] = useState(0)
  const [updateError, setUpdateError] = useState<string | null>(null)
  const updateLogRef = useRef<HTMLDivElement>(null)

  // Ingest state
  const [ingestRunning, setIngestRunning] = useState(false)
  const [ingestLog, setIngestLog] = useState<Array<{ work: string; status: string }>>([])
  const [ingestCounts, setIngestCounts] = useState<{ added: number; updated: number; unchanged: number } | null>(null)
  const [ingestTotal, setIngestTotal] = useState<number | null>(null)
  const [ingestError, setIngestError] = useState<string | null>(null)
  const [ingestLabel, setIngestLabel] = useState('')
  const ingestLogRef = useRef<HTMLDivElement>(null)
  const [pipelineRunning, setPipelineRunning] = useState(false)
  const [phaseProgress, setPhaseProgress] = useState<PhaseProgress[]>([])
  const [pipelineError, setPipelineError] = useState<string | null>(null)

  // Batch ingest state
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchLog, setBatchLog] = useState<{ work: string; status: string }[]>([])
  const [batchCounts, setBatchCounts] = useState<{ added: number; updated: number; unchanged: number; batches: number; fetched: number } | null>(null)
  const [batchPipelinePhases, setBatchPipelinePhases] = useState<PhaseProgress[]>([])
  const [batchError, setBatchError] = useState<string | null>(null)
  const [batchStopping, setBatchStopping] = useState(false)
  const batchLogRef = useRef<HTMLDivElement>(null)

  // Works table sort + pagination state
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [worksPage, setWorksPage] = useState(0)
  const WORKS_PAGE_SIZE = 50
  const [expandedDescs, setExpandedDescs] = useState<Set<string>>(new Set())
  const toggleDesc = (id: string) => setExpandedDescs(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  // AI rating state
  const [aiRatingStarting, setAiRatingStarting] = useState(false)
  const [aiRatingStopping, setAiRatingStopping] = useState(false)
  const [aiRatingError, setAiRatingError] = useState<string | null>(null)

  const { data: project, isLoading } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId!),
  })

  const { data: worksData, isFetching: worksFetching } = useQuery({
    queryKey: ['works', projectId, sortBy, sortDir, worksPage],
    queryFn: () => api.works.list(projectId!, undefined, sortBy ?? undefined, sortDir, WORKS_PAGE_SIZE, worksPage * WORKS_PAGE_SIZE),
    enabled: !!projectId,
    placeholderData: (prev) => prev,
  })
  const works = worksData?.items ?? []
  const worksTotal = worksData?.total ?? 0

  const { data: aiRatingStatus, refetch: refetchAiStatus } = useQuery({
    queryKey: ['ai-rating-status', projectId],
    queryFn: () => api.aiRating.status(projectId!),
    refetchInterval: (query) => {
      const d = query.state.data as AIRatingStatus | undefined
      return d?.running ? 3000 : false
    },
    enabled: !!projectId,
  })

  const { data: crystalliseStatus } = useQuery({
    queryKey: ['crystallise-status', projectId],
    queryFn: () => api.profile.crystalliseStatus(projectId!),
    refetchInterval: (query) => query.state.data?.running ? 2000 : false,
    enabled: !!projectId,
  })

  useEffect(() => {
    if (aiRatingStopping && aiRatingStatus && !aiRatingStatus.running) {
      setAiRatingStopping(false)
    }
  }, [aiRatingStopping, aiRatingStatus])

  const { data: ratings } = useQuery({
    queryKey: ['ratings', projectId],
    queryFn: () => api.ratings.list(projectId!),
    enabled: !!projectId,
  })

  const removeWork = useMutation({
    mutationFn: (ref: string) => api.works.delete(projectId!, ref),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['works', projectId] })
      qc.invalidateQueries({ queryKey: ['ratings', projectId] })
    },
  })


  // Check server for background update status; only poll while a job is actually running
  const { data: updateStatus, refetch: refetchUpdateStatus } = useQuery({
    queryKey: ['update-plugin-status', projectId],
    queryFn: () => api.works.getUpdateStatus(projectId!),
    refetchInterval: (query) => query.state.data?.running ? 4000 : false,
    enabled: !!projectId,
  })
  const serverRunning = updateStatus?.running ?? false

  const { data: batchStatus, refetch: refetchBatchStatus } = useQuery({
    queryKey: ['batch-ingest-status', projectId],
    queryFn: () => api.batchIngest.status(projectId!),
    enabled: !!projectId,
  })

  // Auto-scroll logs
  useEffect(() => {
    if (updateLogRef.current) updateLogRef.current.scrollTop = updateLogRef.current.scrollHeight
  }, [updateLog])
  useEffect(() => {
    if (ingestLogRef.current) ingestLogRef.current.scrollTop = ingestLogRef.current.scrollHeight
  }, [ingestLog])
  useEffect(() => {
    if (batchLogRef.current) batchLogRef.current.scrollTop = batchLogRef.current.scrollHeight
  }, [batchLog])

  const runIngest = async (pluginName: string, config: Record<string, unknown>) => {
    const plugin = (await api.plugins.list()).find(p => p.name === pluginName)
    setIngestLabel(plugin?.title || pluginName)
    setIngestRunning(true)
    setIngestLog([])
    setIngestCounts(null)
    setIngestTotal(null)
    setIngestError(null)
    setUpdateCounts(null)
    setUpdateError(null)
    let hadChanges = false
    let hadError = false
    try {
      await api.works.ingestPluginStream(projectId!, pluginName, config, (event: PluginIngestEvent) => {
        if ('total' in event) {
          setIngestTotal(event.total)
        } else if ('error' in event) {
          hadError = true
          setIngestError(event.error)
          setIngestRunning(false)
        } else if ('complete' in event) {
          hadChanges = event.added > 0 || event.updated > 0
          setIngestCounts({ added: event.added, updated: event.updated, unchanged: event.skipped })
          setIngestRunning(false)
          qc.invalidateQueries({ queryKey: ['works', projectId] })
        } else if ('work' in event) {
          setIngestLog(l => [...l, { work: event.work, status: event.status }])
          setIngestCounts({ added: event.added, updated: event.updated, unchanged: event.skipped })
        }
      })
    } catch (e) {
      hadError = true
      setIngestError(e instanceof Error ? e.message : String(e))
      setIngestRunning(false)
    }
    if (!hadError && hadChanges) runPipeline()
  }

  const runUpdate = async () => {
    setIngestCounts(null)
    setIngestError(null)
    setUpdateRunning(true)
    refetchUpdateStatus()
    setUpdateLog([])
    setUpdateCounts(null)
    setUpdatePhase(null)
    setUpdateFetchTotal(0)
    setUpdateError(null)
    let hadChanges = false
    let hadError = false
    try {
      await api.works.updatePluginStream(projectId!, (event: UpdatePluginEvent) => {
        if ('phase' in event) {
          setUpdatePhase(event.phase)
          if (event.phase === 'fetching') setUpdateFetchTotal((event as any).needs_update)
        } else if ('work' in event) {
          setUpdateLog(l => [...l, { work: event.work, status: event.status }])
          setUpdateCounts({ updated: event.updated, unchanged: event.unchanged })
        } else if ('complete' in event) {
          hadChanges = event.updated > 0
          setUpdateCounts({ updated: event.updated, unchanged: event.unchanged })
          setUpdatePhase(null)
          qc.invalidateQueries({ queryKey: ['works', projectId] })
          qc.invalidateQueries({ queryKey: ['update-plugin-status', projectId] })
        } else if ('error' in event) {
          hadError = true
          setUpdateError(event.error)
        }
      })
    } catch (e) {
      hadError = true
      setUpdateError(e instanceof Error ? e.message : String(e))
    } finally {
      setUpdateRunning(false)
    }
    if (!hadError && hadChanges) runPipeline()
  }

  const startBatchIngest = async () => {
    // Reset any prior run state then launch a fresh batch stream
    try { await api.batchIngest.reset(projectId!) } catch { /* no state yet */ }
    await refetchBatchStatus()
    runBatchIngest()
  }

  const runBatchIngest = async () => {
    setBatchRunning(true)
    setBatchError(null)
    setBatchLog([])
    setBatchCounts(null)
    setBatchPipelinePhases([])
    setBatchStopping(false)
    try {
      await api.batchIngest.startStream(projectId!, (event: BatchIngestEvent) => {
        if (event.type === 'batch_start') {
          setBatchPipelinePhases([])
        } else if (event.type === 'item') {
          setBatchLog(l => [...l.slice(-199), { work: event.work, status: event.status }])
        } else if (event.type === 'batch_done') {
          setBatchCounts({ added: event.total_added, updated: event.total_updated, unchanged: event.total_unchanged, batches: event.batch, fetched: event.total_fetched })
        } else if (event.type === 'pipeline_start') {
          setBatchPipelinePhases(PHASES.map(p => ({ phase: p, status: 'waiting' })))
        } else if (event.type === 'pipeline_phase') {
          const phaseName = event.phase
          const st = event.status
          setBatchPipelinePhases(prev => prev.map(p =>
            p.phase !== phaseName ? p :
            st === 'running' ? { ...p, status: 'running' as PhaseStatus, total: event.total } :
            st === 'progress' ? { ...p, status: 'running' as PhaseStatus, current: event.current, total: event.total } :
            st === 'done' ? { ...p, status: 'done' as PhaseStatus, current: undefined } :
            { ...p, status: 'error' as PhaseStatus }
          ))
        } else if (event.type === 'pipeline_done') {
          qc.invalidateQueries({ queryKey: ['works', projectId] })
        } else if (event.type === 'complete' || event.type === 'paused') {
          qc.invalidateQueries({ queryKey: ['works', projectId] })
          refetchBatchStatus()
        } else if (event.type === 'error') {
          setBatchError(event.error)
        }
      })
    } catch (e) {
      setBatchError(e instanceof Error ? e.message : String(e))
    } finally {
      setBatchRunning(false)
      setBatchStopping(false)
      refetchBatchStatus()
    }
  }

  const runPipeline = async () => {
    if (pipelineRunning) return
    setPipelineRunning(true)
    setPipelineError(null)
    setPhaseProgress(PHASES.map(p => ({ phase: p, status: 'waiting' })))
    try {
      await api.pipeline.runStream(projectId!, (event: PipelineStreamEvent) => {
        if ('phase' in event) {
          if (event.status === 'running') {
            setPhaseProgress(prev => prev.map(p =>
              p.phase === event.phase ? { ...p, status: 'running', total: event.total } : p
            ))
          } else if (event.status === 'progress') {
            setPhaseProgress(prev => prev.map(p =>
              p.phase === event.phase ? { ...p, current: event.current, total: event.total } : p
            ))
          } else if (event.status === 'done') {
            setPhaseProgress(prev => prev.map(p =>
              p.phase === event.phase ? { ...p, status: 'done', items: event.items_processed, current: undefined } : p
            ))
          } else if (event.status === 'error') {
            setPhaseProgress(prev => prev.map(p =>
              p.phase === event.phase ? { ...p, status: 'error' } : p
            ))
            setPipelineError(event.error)
          }
        }
        if ('complete' in event) {
          qc.invalidateQueries({ queryKey: ['works', projectId] })
        }
      })
    } catch (e) {
      setPipelineError(e instanceof Error ? e.message : String(e))
    } finally {
      setPipelineRunning(false)
    }
  }

  const isMobile = useIsMobile()

  if (isLoading || !project) return <p>Loading…</p>

  const pipelineDone = phaseProgress.length > 0 && !pipelineRunning && !pipelineError

  const handleSort = (col: string | null) => {
    if (sortBy === col) { setSortDir(d => d === 'asc' ? 'desc' : 'asc'); setWorksPage(0); return }
    setSortBy(col)
    setSortDir(col === null ? 'asc' : 'desc')
    setWorksPage(0)
  }

  const sortIndicator = (col: string | null) =>
    sortBy === col ? (sortDir === 'asc' ? ' ▴' : ' ▾') : ''

  const thSort: React.CSSProperties = { padding: '6px 8px', cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap', verticalAlign: 'bottom' }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <Link to="/">← Projects</Link>
          <h2 style={{ margin: '8px 0 4px' }}>{project.name}</h2>
          {project.description && <p style={{ margin: 0, color: 'var(--text-muted)' }}>{project.description}</p>}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <a
            href={api.projects.exportUrl(project.id)}
            download
            title="Export project"
            style={{ width: '2.4em', height: '2.4em', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.1em', border: '1px solid var(--border)', borderRadius: 6, textDecoration: 'none', color: 'inherit', background: 'none' }}
          >↓</a>
          <button
            onClick={() => setShowSettings(true)}
            title="Project settings"
            style={{ width: '2.4em', height: '2.4em', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.2em' }}
          >⚙</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{worksTotal}</div>
          <div style={{ color: 'var(--text-muted)' }}>Works</div>
        </div>
        {(() => {
          const nonSkipped = ratings?.filter(r => !r.skipped) ?? []
          const humanCount = nonSkipped.filter(r => !r.is_ai).length
          const aiCount = nonSkipped.filter(r => r.is_ai).length
          const hasConfidence = (project.profile_confirmed_count ?? 0) > 0 && project.profile_confidence != null
          const pct = hasConfidence ? Math.round((project.profile_confidence as number) * 100) : null
          const minConf = project.min_profile_confidence ?? 0.9
          const hasEnough = (project.profile_confirmed_count ?? 0) >= project.crystallisation_threshold
          return (
            <div
              onClick={() => setRatedChunksFilter({})}
              style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16, flex: 1, cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover, rgba(128,128,128,0.06))')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >
              <div>
                <div style={{ fontSize: 28, fontWeight: 700 }}>{nonSkipped.length}</div>
                <div style={{ color: 'var(--text-muted)' }}>Ratings</div>
              </div>
              <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
                <span>{humanCount} human</span>
                <span>{aiCount} AI</span>
                {pct !== null && (
                  <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
                    <span style={{ padding: '2px 7px', borderRadius: 10, background: 'var(--surface, rgba(128,128,128,0.08))', fontWeight: 500 }}>
                      {pct}% accuracy
                    </span>
                    {hasEnough && (project.profile_confidence as number) < minConf && (
                      <span style={{ padding: '2px 7px', borderRadius: 10, background: 'rgba(245,158,11,0.12)', color: '#b45309', fontWeight: 600 }}>
                        re-crystallize
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })()}
      </div>

      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button
          onClick={() => setShowPluginIngest(true)}
          disabled={ingestRunning || batchRunning}
          style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: (ingestRunning || batchRunning) ? 'default' : 'pointer', fontSize: 14 }}
        >
          {ingestRunning ? 'Ingesting…' : 'Ingest'}
        </button>
        <button
          onClick={async () => {
            if (batchStatus?.supported) {
              await api.batchIngest.reset(projectId!)
              await refetchBatchStatus()
              runBatchIngest()
            } else {
              runUpdate()
            }
          }}
          disabled={updateRunning || serverRunning || batchRunning}
          style={{ padding: '8px 18px', background: 'none', border: '1px solid #6b7de0', color: '#6b7de0', borderRadius: 6, cursor: (updateRunning || serverRunning || batchRunning) ? 'default' : 'pointer', fontSize: 14 }}
        >
          {updateRunning ? 'Updating…' : batchRunning ? 'Importing…' : serverRunning && !updateRunning ? 'Update running…' : 'Update'}
        </button>
        {(batchRunning || batchStopping) && (
          <button
            onClick={async () => { setBatchStopping(true); await api.batchIngest.stop(projectId!) }}
            disabled={batchStopping}
            style={{ padding: '8px 18px', background: 'none', border: '1px solid #f59e0b', color: '#b45309', borderRadius: 6, cursor: batchStopping ? 'default' : 'pointer', fontSize: 14 }}
          >
            {batchStopping ? 'Stopping…' : 'Stop'}
          </button>
        )}
        {!batchRunning && !batchStopping && batchStatus?.supported && batchStatus.status === 'paused' && (
          <button
            onClick={runBatchIngest}
            style={{ padding: '8px 18px', background: 'none', border: '1px solid #6b7de0', color: '#6b7de0', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
          >
            Resume
          </button>
        )}
        <span style={{ color: 'var(--border, #ddd)', fontSize: 18, userSelect: 'none' }}>›</span>
        <Link to={`/projects/${projectId}/rate${(aiRatingStatus?.unconfirmed_ai_count ?? 0) > 0 ? '?mode=confirm_ai' : ''}`}>
          <button style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border, #ddd)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}>
            Rate{(aiRatingStatus?.unconfirmed_ai_count ?? 0) > 0 ? ` (${aiRatingStatus!.unconfirmed_ai_count} AI)` : ''}
          </button>
        </Link>
        <span style={{ color: 'var(--border, #ddd)', fontSize: 18, userSelect: 'none' }}>›</span>
        <div style={{ position: 'relative' }}>
          <Link to={`/projects/${projectId}/profile`}>
            <button style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border, #ddd)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}>
              Profile
            </button>
          </Link>
          {(() => {
            const humanCount = ratings?.filter(r => !r.skipped && !r.is_ai).length ?? 0
            const need = project.crystallisation_threshold - humanCount
            return need > 0 ? (
              <span style={{ position: 'absolute', top: 'calc(100% + 3px)', left: 0, fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                {need} more to crystallise
              </span>
            ) : null
          })()}
        </div>

        <span style={{ color: 'var(--border, #ddd)', fontSize: 18, userSelect: 'none' }}>›</span>

        {/* AI Rating controls */}
        {aiRatingStatus?.running || aiRatingStopping ? (
          <button
            onClick={async () => {
              setAiRatingStopping(true)
              try {
                await api.aiRating.stop(projectId!)
                refetchAiStatus()
              } catch {
                setAiRatingStopping(false)
              }
            }}
            disabled={aiRatingStopping}
            style={{ padding: '8px 18px', background: 'none', border: '1px solid #f59e0b', color: '#b45309', borderRadius: 6, cursor: aiRatingStopping ? 'default' : 'pointer', fontSize: 14 }}
          >
            {aiRatingStopping ? 'Stopping…' : 'Stop AI Rating'}
          </button>
        ) : (
          <button
            onClick={async () => {
              setAiRatingStarting(true)
              setAiRatingError(null)
              try {
                await api.aiRating.start(projectId!)
                refetchAiStatus()
              } catch (e: any) {
                const msg = e?.message ?? String(e)
                if (msg.includes('No crystallised profile')) {
                  setAiRatingError('Crystallise a profile first before starting AI rating.')
                } else if (e?.status === 409) {
                  setAiRatingError('AI rating is already running.')
                } else {
                  setAiRatingError(msg)
                }
              } finally {
                setAiRatingStarting(false)
              }
            }}
            disabled={aiRatingStarting || !ratings}
            title={!ratings ? 'Load profile first' : 'Start AI background rating'}
            style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border, #ddd)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
          >
            {aiRatingStarting ? 'Starting…' : 'AI Rating'}
          </button>
        )}

        {/* Ingest progress */}
        {(ingestRunning || ingestCounts || ingestError) && (
          <div style={{ width: '100%', marginTop: 8, fontSize: 13 }}>
            {ingestRunning && (
              <p style={{ margin: '0 0 4px', color: '#6b7de0' }}>
                {ingestLabel ? `Ingesting ${ingestLabel}` : 'Ingesting'}
                {ingestCounts && ingestTotal
                  ? ` — ${ingestCounts.added + ingestCounts.updated + ingestCounts.unchanged} of ${ingestTotal}`
                  : ingestCounts
                  ? ` — ${ingestCounts.added + ingestCounts.updated + ingestCounts.unchanged} items`
                  : '…'}
              </p>
            )}
            {(ingestRunning || (!ingestCounts && ingestLog.length > 0)) && ingestLog.length > 0 && (
              <div ref={ingestLogRef} style={{ height: 42, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 4, padding: '4px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                {ingestLog.map((e, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, lineHeight: '19px' }}>
                    <span style={{ color: e.status === 'added' ? '#2e7d32' : e.status === 'updated' ? '#6b7de0' : 'var(--text-muted)', width: 12 }}>
                      {e.status === 'added' ? '+' : e.status === 'updated' ? '↑' : '·'}
                    </span>
                    <span style={{ color: e.status === 'unchanged' ? 'var(--text-muted)' : 'inherit' }}>{e.work}</span>
                  </div>
                ))}
              </div>
            )}
            {ingestCounts && !ingestRunning && !ingestError && (
              <p style={{ margin: '4px 0 0', color: '#390' }}>
                Done — {ingestCounts.added} added, {ingestCounts.updated} updated, {ingestCounts.unchanged} unchanged
              </p>
            )}
            {ingestError && <p style={{ margin: '4px 0 0', color: '#c00' }}>{ingestError}</p>}
          </div>
        )}

        {/* Update progress */}
        {(updateRunning || serverRunning || updateCounts || updateError) && (
          <div style={{ width: '100%', marginTop: 8, fontSize: 13 }}>
            {updateRunning && updatePhase === 'checking' && (
              <p style={{ margin: '0 0 4px', color: '#6b7de0' }}>Checking for updates…</p>
            )}
            {updateRunning && updatePhase === 'fetching' && (
              <p style={{ margin: '0 0 4px', color: '#6b7de0' }}>
                Fetching {updateLog.length} of {updateFetchTotal} works…
              </p>
            )}
            {serverRunning && !updateRunning && (
              <p style={{ margin: '0 0 4px', color: '#6b7de0' }}>
                Update running in background
                {updateStatus && updateStatus.updated + updateStatus.unchanged > 0
                  ? ` — ${updateStatus.updated} updated, ${updateStatus.unchanged} checked`
                  : '…'}
              </p>
            )}
            {updateRunning && updateLog.length > 0 && (
              <div ref={updateLogRef} style={{ height: 42, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 4, padding: '4px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                {updateLog.map((e, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, lineHeight: '19px' }}>
                    <span style={{ color: e.status === 'updated' ? '#2e7d32' : 'var(--text-muted)', width: 12 }}>
                      {e.status === 'updated' ? '↑' : '·'}
                    </span>
                    <span style={{ color: e.status === 'updated' ? 'inherit' : 'var(--text-muted)' }}>{e.work}</span>
                  </div>
                ))}
              </div>
            )}
            {updateCounts && !updateRunning && !updateError && (
              <p style={{ margin: '4px 0 0', color: '#390' }}>
                Done — {updateCounts.updated} updated, {updateCounts.unchanged} unchanged
              </p>
            )}
            {updateError && <p style={{ margin: '4px 0 0', color: '#c00' }}>{updateError}</p>}
          </div>
        )}

        {/* Batch ingest progress */}
        {(batchRunning || batchCounts || batchError) && (
          <div style={{ width: '100%', marginTop: 8, fontSize: 13 }}>
            {batchRunning && (
              <p style={{ margin: '0 0 4px', color: '#6b7de0' }}>
                Batch import — {batchCounts ? `batch ${batchCounts.batches}, ${batchCounts.fetched} fetched` : 'starting…'}
                {batchStopping && ' (stopping after this batch…)'}
              </p>
            )}
            {batchRunning && batchLog.length > 0 && (
              <div ref={batchLogRef} style={{ height: 42, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 4, padding: '4px 10px', display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 4 }}>
                {batchLog.map((e, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, lineHeight: '19px' }}>
                    <span style={{ color: e.status === 'added' ? '#2e7d32' : e.status === 'updated' ? '#6b7de0' : 'var(--text-muted)', width: 12 }}>
                      {e.status === 'added' ? '+' : e.status === 'updated' ? '↑' : '·'}
                    </span>
                    <span style={{ color: e.status === 'unchanged' ? 'var(--text-muted)' : 'inherit', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.work}</span>
                  </div>
                ))}
              </div>
            )}
            {batchRunning && batchPipelinePhases.length > 0 && (
              <PipelineProgress phases={batchPipelinePhases} />
            )}
            {!batchRunning && batchCounts && !batchError && (
              <p style={{ margin: '4px 0 0', color: batchStatus?.supported && batchStatus.status === 'paused' ? '#b45309' : '#390' }}>
                {batchStatus?.supported && batchStatus.status === 'paused'
                  ? `Paused after batch ${batchCounts.batches} — ${batchCounts.fetched} fetched · ${batchCounts.added} added, ${batchCounts.updated} updated`
                  : `Done — ${batchCounts.batches} batches · ${batchCounts.added} added, ${batchCounts.updated} updated, ${batchCounts.unchanged} unchanged`}
              </p>
            )}
            {batchError && <p style={{ margin: '4px 0 0', color: '#c00' }}>{batchError}</p>}
            {!batchRunning && batchStatus?.supported &&
              (batchStatus.status === 'paused' || batchStatus.status === 'done' || batchStatus.status === 'error') && (
              <button
                onClick={async () => { await api.batchIngest.reset(projectId!); refetchBatchStatus(); setBatchCounts(null); setBatchError(null); setBatchLog([]) }}
                style={{ marginTop: 4, padding: '4px 12px', background: 'none', border: '1px solid var(--border, #ddd)', color: 'var(--text-muted)', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
              >
                Reset
              </button>
            )}
          </div>
        )}

        {/* Crystallise status */}
        {crystalliseStatus?.running && (
          <div style={{ width: '100%', marginTop: 8, fontSize: 13 }}>
            <p style={{ margin: 0, color: '#6b7de0' }}>
              ⟳ Crystallising…
              {tokenLabel(crystalliseStatus.tokens_prompt, crystalliseStatus.tokens_completion) && (
                <span style={{ marginLeft: 8, color: 'var(--text-muted)' }}>
                  · {tokenLabel(crystalliseStatus.tokens_prompt, crystalliseStatus.tokens_completion)} tokens used
                </span>
              )}
            </p>
          </div>
        )}

        {/* AI rating status */}
        {aiRatingStatus && (aiRatingStatus.running || aiRatingStatus.stopped_reason || aiRatingStatus.chunks_rated > 0) && (
          <div style={{ width: '100%', marginTop: 8, fontSize: 13 }}>
            {aiRatingStatus.running && (
              <p style={{ margin: 0, color: '#6b7de0' }}>
                AI Rating · {aiRatingStatus.chunks_rated} chunks scored · batch {aiRatingStatus.batches_completed}
                {aiRatingStatus.last_batch_avg != null && ` · avg ${aiRatingStatus.last_batch_avg.toFixed(2)}`}
                {tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion) && (
                  <span style={{ marginLeft: 8, color: 'var(--text-muted)' }}>
                    · {tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion)} tokens
                  </span>
                )}
              </p>
            )}
            {!aiRatingStatus.running && aiRatingStatus.stopped_reason === 'diminishing_returns' && (
              <p style={{ margin: 0, color: 'var(--text-muted)' }}>
                AI Rating done — {aiRatingStatus.chunks_rated} chunks scored · interesting chunks exhausted
                {tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion) && ` · ${tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion)} tokens`}
              </p>
            )}
            {!aiRatingStatus.running && aiRatingStatus.stopped_reason === 'complete' && (
              <p style={{ margin: 0, color: '#390' }}>
                AI Rating complete — {aiRatingStatus.chunks_rated} chunks scored
                {tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion) && ` · ${tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion)} tokens`}
              </p>
            )}
            {!aiRatingStatus.running && aiRatingStatus.stopped_reason === 'user_stopped' && (
              <p style={{ margin: 0, color: 'var(--text-muted)' }}>
                AI Rating stopped · {aiRatingStatus.chunks_rated} chunks scored
                {tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion) && ` · ${tokenLabel(aiRatingStatus.tokens_prompt, aiRatingStatus.tokens_completion)} tokens`}
              </p>
            )}
            {aiRatingStatus.profile_stale && (
              <p style={{ margin: '2px 0 0', color: '#b45309', fontSize: 12 }}>
                Profile updated — AI scores may be stale. Restart AI Rating to refresh.
              </p>
            )}
          </div>
        )}
        {aiRatingError && (
          <p style={{ margin: '8px 0 0', fontSize: 13, color: '#c00', width: '100%' }}>{aiRatingError}</p>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>Works</h3>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sort</span>
          <select
            value={sortBy ?? ''}
            onChange={e => { setSortBy(e.target.value || null); if (!e.target.value) setSortDir('asc'); setWorksPage(0) }}
            style={{ fontSize: 12, padding: '3px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg, #1a1a1a)', color: 'var(--text)', cursor: 'pointer' }}
          >
            <option value="">Work #</option>
            <option value="name">Work name</option>
            <option value="ingested_at">Ingestion date</option>
            <option value="pipeline_phase">Status</option>
            <option value="human_rated">Human rated</option>
            <option value="ai_rated">AI rated</option>
            <optgroup label="Overall">
              <option value="overall:avg">Overall avg</option>
              <option value="overall:max">Overall max</option>
              <option value="overall:min">Overall min</option>
            </optgroup>
            {project.rating_dimensions.map(d => (
              <optgroup key={d.name} label={d.name}>
                <option value={`dim:${d.name}:avg`}>{d.name} avg</option>
                <option value={`dim:${d.name}:max`}>{d.name} max</option>
                <option value={`dim:${d.name}:min`}>{d.name} min</option>
              </optgroup>
            ))}
          </select>
          <button
            onClick={() => { setSortDir(d => d === 'asc' ? 'desc' : 'asc'); setWorksPage(0) }}
            style={{ fontSize: 12, padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: 'var(--text)', cursor: 'pointer' }}
          >
            {sortDir === 'asc' ? '▴ Asc' : '▾ Desc'}
          </button>
        </div>
      </div>

      {phaseProgress.length > 0 && (
        <PipelineProgress
          phases={phaseProgress}
          error={pipelineError ?? undefined}
        />
      )}
      {pipelineDone && (
        <p style={{ color: '#390', fontSize: 13, margin: '4px 0 6px' }}>
          Processing complete — {phaseProgress.find(p => p.phase === 'cluster')?.items ?? 0} items
        </p>
      )}

      {isMobile ? (
        /* ── Mobile: card list ─────────────────────────────────────── */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
          {works.map(w => {
            const hasRatings = w.overall_avg != null
            const openChunks = () => setRatedChunksFilter({ workSeq: w.project_seq ?? undefined, title: w.work_title ?? undefined })
            const openDetail = () => setDetailWorkRef(w.project_seq ?? w.id)
            const ratingParts = [
              (w.human_rated ?? 0) > 0 ? `Human ${w.human_rated}` : null,
              (w.ai_rated ?? 0) > 0 ? `AI ${w.ai_rated}` : null,
            ].filter(Boolean)
            return (
              <div
                key={w.id}
                onClick={openDetail}
                style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover, rgba(128,128,128,0.06))')}
                onMouseLeave={e => (e.currentTarget.style.background = '')}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>#{w.project_seq}</span>
                    <span
                      title={w.work_title ?? w.source_path?.split('/').pop() ?? w.id}
                      style={{ fontWeight: 500, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      {w.work_title ?? w.source_path?.split('/').pop() ?? w.id}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    <span style={{
                      background: w.pipeline_phase === 'clustered' ? 'var(--badge-green-bg)' : 'var(--badge-yellow-bg)',
                      color: w.pipeline_phase === 'clustered' ? 'var(--badge-green-text)' : 'var(--badge-yellow-text)',
                      padding: '1px 5px', borderRadius: 3,
                    }}>
                      {PIPELINE_PHASE_DISPLAY[w.pipeline_phase] ?? w.pipeline_phase}
                    </span>
                    {ratingParts.length > 0 && <span>{ratingParts.join(' · ')}</span>}
                  </div>
                  {w.first_description && (
                    <div
                      onClick={e => { e.stopPropagation(); toggleDesc(w.id) }}
                      style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', cursor: 'pointer', lineHeight: 1.4 }}
                    >
                      {expandedDescs.has(w.id) ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          {(w.chunk_descriptions ?? []).map(cd => (
                            <div key={cd.position}>
                              <span style={{ fontStyle: 'normal', fontWeight: 500 }}>chunk {cd.position + 1}:</span> {cd.description}
                            </div>
                          ))}
                          <span style={{ fontSize: 10 }}>▴ collapse</span>
                        </div>
                      ) : (
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          <span style={{ fontSize: 10, marginRight: 3, fontStyle: 'normal' }}>▾</span>{w.first_description}
                        </div>
                      )}
                    </div>
                  )}
                  {hasRatings && (
                    <button
                      onClick={e => { e.stopPropagation(); openChunks() }}
                      style={{ marginTop: 8, padding: '6px 12px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: '#6b7de0', fontSize: 12, cursor: 'pointer' }}
                    >
                      Ratings · avg <span style={{ color: thermalColor(w.overall_avg!), fontWeight: 600 }}>{w.overall_avg!.toFixed(1)}</span>
                    </button>
                  )}
                </div>
                <span style={{ color: 'var(--text-muted)', fontSize: 18, flexShrink: 0 }}>›</span>
              </div>
            )
          })}
        </div>
      ) : (
        /* ── Desktop: dimensional table ────────────────────────────── */
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 4, tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: 36 }} />
              <col />
              {project.rating_dimensions.map(d => <col key={d.name} style={{ width: 52 }} />)}
              <col style={{ width: 60 }} />
            </colgroup>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border)', textAlign: 'left', height: 100 }}>
                <th onClick={() => handleSort('seq')} style={{ ...thSort, paddingLeft: 4 }}>
                  #{sortIndicator('seq')}
                </th>
                <th onClick={() => handleSort('name')} style={thSort}>
                  Work{sortIndicator('name')}
                </th>
                {project.rating_dimensions.map(d => {
                  const dimActive = sortBy?.startsWith(`dim:${d.name}:`) ?? false
                  return (
                    <th
                      key={d.name}
                      onClick={() => handleSort(`dim:${d.name}:avg`)}
                      style={{ padding: '0 0 12px 10px', verticalAlign: 'bottom', overflow: 'visible', cursor: 'pointer', userSelect: 'none' }}
                    >
                      <div style={{
                        display: 'inline-block',
                        transform: 'rotate(-45deg)',
                        transformOrigin: '0 100%',
                        whiteSpace: 'nowrap',
                        fontSize: 12,
                        fontWeight: 500,
                        lineHeight: 1,
                        color: dimActive ? 'var(--text)' : 'var(--text-muted)',
                      }}>
                        {d.name}{dimActive ? (sortDir === 'asc' ? ' ▴' : ' ▾') : ''}
                      </div>
                    </th>
                  )
                })}
                <th onClick={() => handleSort('overall:avg')} style={{ ...thSort, textAlign: 'right' }}>
                  Avg{sortIndicator('overall:avg')}
                </th>
              </tr>
            </thead>
            <tbody>
              {works.map(w => {
                const hasRatings = w.overall_avg != null
                const openChunks = () => setRatedChunksFilter({ workSeq: w.project_seq ?? undefined, title: w.work_title ?? undefined })
                const openDetail = () => setDetailWorkRef(w.project_seq ?? w.id)
                const ratingParts = [
                  (w.human_rated ?? 0) > 0 ? `Human ${w.human_rated}` : null,
                  (w.ai_rated ?? 0) > 0 ? `AI ${w.ai_rated}` : null,
                ].filter(Boolean)
                return (
                  <tr key={w.id} style={{ borderBottom: '1px solid var(--border)', verticalAlign: 'top' }}>
                    <td
                      onClick={openDetail}
                      style={{ padding: '8px 4px', color: 'var(--text-muted)', fontSize: 12, whiteSpace: 'nowrap', cursor: 'pointer' }}
                    >
                      #{w.project_seq}
                    </td>
                    <td
                      onClick={openDetail}
                      style={{ padding: '8px 10px 8px 8px', overflow: 'hidden', cursor: 'pointer' }}
                    >
                      <div
                        title={w.work_title ?? w.source_path?.split('/').pop() ?? w.id}
                        style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500, fontSize: 13 }}
                      >
                        {w.work_title ?? w.source_path?.split('/').pop() ?? w.id}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                        <span style={{
                          background: w.pipeline_phase === 'clustered' ? 'var(--badge-green-bg)' : 'var(--badge-yellow-bg)',
                          color: w.pipeline_phase === 'clustered' ? 'var(--badge-green-text)' : 'var(--badge-yellow-text)',
                          padding: '1px 5px', borderRadius: 3,
                        }}>
                          {PIPELINE_PHASE_DISPLAY[w.pipeline_phase] ?? w.pipeline_phase}
                        </span>
                        {ratingParts.length > 0 && <span>Ratings: {ratingParts.join(', ')}</span>}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                        {w.ingested_at.slice(0, 10)}
                      </div>
                      {w.first_description && (
                        <div
                          onClick={e => { e.stopPropagation(); toggleDesc(w.id) }}
                          style={{ marginTop: 3, fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', cursor: 'pointer', lineHeight: 1.4 }}
                        >
                          {expandedDescs.has(w.id) ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, whiteSpace: 'normal' }}>
                              {(w.chunk_descriptions ?? []).map(cd => (
                                <div key={cd.position}>
                                  <span style={{ fontStyle: 'normal', fontWeight: 500 }}>chunk {cd.position + 1}:</span> {cd.description}
                                </div>
                              ))}
                              <span style={{ fontSize: 10 }}>▴ collapse</span>
                            </div>
                          ) : (
                            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              <span style={{ fontSize: 10, marginRight: 3, fontStyle: 'normal' }}>▾</span>{w.first_description}
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    {project.rating_dimensions.map(d => {
                      const ds = w.dim_stats?.[d.name]
                      return (
                        <td
                          key={d.name}
                          onClick={hasRatings ? openChunks : undefined}
                          style={{ padding: '8px 4px', textAlign: 'right', whiteSpace: 'nowrap', cursor: hasRatings ? 'pointer' : 'default' }}
                        >
                          {ds ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-end' }}>
                              <span style={{ color: thermalColor(ds.max), fontSize: 12 }}>{ds.max.toFixed(1)}</span>
                              <span style={{ color: thermalColor(ds.avg), fontSize: 12 }}>{ds.avg.toFixed(1)}</span>
                              <span style={{ color: thermalColor(ds.min), fontSize: 12 }}>{ds.min.toFixed(1)}</span>
                            </div>
                          ) : (
                            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>
                          )}
                        </td>
                      )
                    })}
                    <td
                      onClick={hasRatings ? openChunks : undefined}
                      style={{ padding: '8px 8px', textAlign: 'right', whiteSpace: 'nowrap', cursor: hasRatings ? 'pointer' : 'default' }}
                    >
                      {hasRatings ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-end' }}>
                          <span style={{ color: thermalColor(w.overall_max!), fontSize: 11 }}>{w.overall_max!.toFixed(1)}</span>
                          <span style={{ color: thermalColor(w.overall_avg!), fontSize: 16, fontWeight: 700, lineHeight: 1 }}>{w.overall_avg!.toFixed(1)}</span>
                          <span style={{ color: thermalColor(w.overall_min!), fontSize: 11 }}>{w.overall_min!.toFixed(1)}</span>
                        </div>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {worksTotal > WORKS_PAGE_SIZE && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, fontSize: 13, color: 'var(--text-muted)' }}>
          <button
            onClick={() => setWorksPage(p => Math.max(0, p - 1))}
            disabled={worksPage === 0}
            style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: worksPage === 0 ? 'var(--text-muted)' : 'var(--text)', cursor: worksPage === 0 ? 'default' : 'pointer' }}
          >← Prev</button>
          <span>
            {worksPage * WORKS_PAGE_SIZE + 1}–{Math.min((worksPage + 1) * WORKS_PAGE_SIZE, worksTotal)} of {worksTotal}
            {worksFetching && <span style={{ marginLeft: 8, opacity: 0.6 }}>loading…</span>}
          </span>
          <button
            onClick={() => setWorksPage(p => p + 1)}
            disabled={(worksPage + 1) * WORKS_PAGE_SIZE >= worksTotal}
            style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: (worksPage + 1) * WORKS_PAGE_SIZE >= worksTotal ? 'var(--text-muted)' : 'var(--text)', cursor: (worksPage + 1) * WORKS_PAGE_SIZE >= worksTotal ? 'default' : 'pointer' }}
          >Next →</button>
        </div>
      )}

      {showSettings && project && (
        <ProjectSettingsDialog
          project={project}
          ratings={ratings ?? []}
          onClose={() => setShowSettings(false)}
        />
      )}

      {showPluginIngest && (
        <PluginIngestDialog
          projectId={projectId!}
          domain={project.domain}
          onClose={() => { setShowPluginIngest(false); refetchUpdateStatus() }}
          onIngest={(pluginName, config) => {
            setShowPluginIngest(false)
            refetchUpdateStatus()
            runIngest(pluginName, config)
          }}
          onBatchIngest={() => {
            setShowPluginIngest(false)
            startBatchIngest()
          }}
        />
      )}

      {detailWorkRef !== null && (
        <WorkDetailModal
          projectId={projectId!}
          workRef={detailWorkRef}
          dimensions={project.rating_dimensions}
          onClose={() => setDetailWorkRef(null)}
          onRemove={ref => { removeWork.mutate(String(ref)); setDetailWorkRef(null) }}
        />
      )}

      {ratedChunksFilter !== null && (
        <RatedChunksModal
          projectId={projectId!}
          filterWorkSeq={ratedChunksFilter.workSeq}
          filterWorkTitle={ratedChunksFilter.title}
          dimensions={project.rating_dimensions}
          onClose={() => setRatedChunksFilter(null)}
        />
      )}

    </div>
  )
}

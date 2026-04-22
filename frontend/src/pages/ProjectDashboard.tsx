import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import ProjectSettingsDialog from '../components/ProjectSettingsDialog'
import PluginIngestDialog from '../components/PluginIngestDialog'
import WorkDetailModal from '../components/WorkDetailModal'
import RatedChunksModal from '../components/RatedChunksModal'
import type { PipelineStreamEvent, PluginIngestEvent, UpdatePluginEvent } from '../api/types'

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

  const { data: project, isLoading } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId!),
  })

  const { data: works } = useQuery({
    queryKey: ['works', projectId],
    queryFn: () => api.works.list(projectId!),
    enabled: !!projectId,
  })

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

  // Auto-scroll logs
  useEffect(() => {
    if (updateLogRef.current) updateLogRef.current.scrollTop = updateLogRef.current.scrollHeight
  }, [updateLog])
  useEffect(() => {
    if (ingestLogRef.current) ingestLogRef.current.scrollTop = ingestLogRef.current.scrollHeight
  }, [ingestLog])

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

  if (isLoading || !project) return <p>Loading…</p>

  // Rated chunk count per material_item_id derived from ratings list
  const ratedPerWork = new Map<string, number>()
  for (const r of ratings ?? []) {
    if (!r.skipped) ratedPerWork.set(r.material_item_id, (ratedPerWork.get(r.material_item_id) ?? 0) + 1)
  }

  const pipelineDone = phaseProgress.length > 0 && !pipelineRunning && !pipelineError

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <Link to="/">← Projects</Link>
          <h2 style={{ margin: '8px 0 4px' }}>{project.name}</h2>
          {project.description && <p style={{ margin: 0, color: 'var(--text-muted)' }}>{project.description}</p>}
        </div>
        <button
          onClick={() => setShowSettings(true)}
          title="Project settings"
          style={{ width: '2.4em', height: '2.4em', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.2em' }}
        >⚙</button>
      </div>

      <div style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{works?.length ?? 0}</div>
          <div style={{ color: 'var(--text-muted)' }}>Works</div>
        </div>
        <div
          onClick={() => setRatedChunksFilter({})}
          style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16, flex: 1, cursor: 'pointer' }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover, rgba(128,128,128,0.06))')}
          onMouseLeave={e => (e.currentTarget.style.background = '')}
        >
          <div style={{ fontSize: 28, fontWeight: 700 }}>{ratings?.filter(r => !r.skipped).length ?? 0}</div>
          <div style={{ color: 'var(--text-muted)' }}>
            Ratings <span style={{ fontSize: 11 }}>(min. {project.crystallisation_threshold})</span>
          </div>
        </div>
      </div>

      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button
          onClick={() => setShowPluginIngest(true)}
          disabled={ingestRunning}
          style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: ingestRunning ? 'default' : 'pointer', fontSize: 14 }}
        >
          {ingestRunning ? 'Ingesting…' : 'Ingest'}
        </button>
        <button
          onClick={runUpdate}
          disabled={updateRunning || serverRunning}
          style={{ padding: '8px 18px', background: 'none', border: '1px solid #6b7de0', color: '#6b7de0', borderRadius: 6, cursor: updateRunning || serverRunning ? 'default' : 'pointer', fontSize: 14 }}
        >
          {updateRunning ? 'Updating…' : serverRunning && !updateRunning ? 'Update running…' : 'Update'}
        </button>
        <span style={{ color: 'var(--border, #ddd)', fontSize: 18, userSelect: 'none' }}>›</span>
        <Link to={`/projects/${projectId}/rate`}>
          <button style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border, #ddd)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}>
            Rate
          </button>
        </Link>
        <span style={{ color: 'var(--border, #ddd)', fontSize: 18, userSelect: 'none' }}>›</span>
        <Link to={`/projects/${projectId}/profile`}>
          <button style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border, #ddd)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}>
            Profile
          </button>
        </Link>

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
      </div>

      <h3 style={{ margin: '0 0 8px' }}>Works</h3>

      {phaseProgress.length > 0 && (
        <PipelineProgress
          phases={phaseProgress}
          error={pipelineError ?? undefined}
        />
      )}
      {pipelineDone && (
        <p style={{ color: '#390', fontSize: 13, margin: '4px 0 8px' }}>
          Processing complete — {phaseProgress.find(p => p.phase === 'cluster')?.items ?? 0} items
        </p>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 12 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--border)', textAlign: 'left' }}>
            <th style={{ padding: '4px 8px' }}>#</th>
            <th style={{ padding: '4px 8px' }}>File</th>
            <th style={{ padding: '4px 8px' }}>Phase</th>
            <th style={{ padding: '4px 8px' }}>Ingested</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Rated</th>
            <th style={{ padding: '4px 8px' }}></th>
            <th style={{ padding: '4px 8px' }}></th>
          </tr>
        </thead>
        <tbody>
          {works?.map(w => (
            <tr key={w.id} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 8px', color: 'var(--text-muted)' }}>#{w.project_seq}</td>
              <td style={{ padding: '4px 8px' }}>
                {w.work_title ?? w.source_path?.split('/').pop() ?? w.id}
              </td>
              <td style={{ padding: '4px 8px' }}>
                <span style={{
                  background: w.pipeline_phase === 'clustered' ? 'var(--badge-green-bg)' : 'var(--badge-yellow-bg)',
                  color: w.pipeline_phase === 'clustered' ? 'var(--badge-green-text)' : 'var(--badge-yellow-text)',
                  padding: '2px 6px', borderRadius: 4, fontSize: 11,
                }}>
                  {PIPELINE_PHASE_DISPLAY[w.pipeline_phase] ?? w.pipeline_phase}
                </span>
              </td>
              <td style={{ padding: '4px 8px', color: 'var(--text-muted)' }}>{w.ingested_at.slice(0, 10)}</td>
              <td style={{ padding: '4px 8px', textAlign: 'right' }}>
                {(() => {
                  const count = ratedPerWork.get(w.id) ?? 0
                  return count > 0 ? (
                    <button
                      onClick={() => setRatedChunksFilter({ workSeq: w.project_seq ?? undefined, title: w.work_title ?? undefined })}
                      style={{ color: '#6b7de0', fontSize: 12, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    >
                      {count}
                    </button>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>
                  )
                })()}
              </td>
              <td style={{ padding: '4px 8px' }}>
                <button
                  onClick={() => setDetailWorkRef(w.project_seq ?? w.id)}
                  style={{ color: '#6b7de0', fontSize: 11, background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  Details
                </button>
              </td>
              <td style={{ padding: '4px 8px' }}>
                <button
                  onClick={() => confirm('Remove this work? Associated ratings will also be deleted.') && removeWork.mutate(String(w.project_seq))}
                  style={{ color: '#c00', fontSize: 11, background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

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
          onClose={() => { setShowPluginIngest(false); refetchUpdateStatus() }}
          onIngest={(pluginName, config) => {
            setShowPluginIngest(false)
            refetchUpdateStatus()
            runIngest(pluginName, config)
          }}
        />
      )}

      {detailWorkRef !== null && (
        <WorkDetailModal
          projectId={projectId!}
          workRef={detailWorkRef}
          onClose={() => setDetailWorkRef(null)}
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

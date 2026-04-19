import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import StorageBrowser from '../components/StorageBrowser'
import ProjectSettingsDialog from '../components/ProjectSettingsDialog'
import PluginIngestDialog from '../components/PluginIngestDialog'
import WorkDetailModal from '../components/WorkDetailModal'
import type { IngestResult, PipelineStreamEvent } from '../api/types'

type PhaseStatus = 'waiting' | 'running' | 'done' | 'error'
type PhaseProgress = { phase: string; status: PhaseStatus; items?: number }

const PHASES = ['chunk', 'embed', 'cluster']

const PHASE_LABELS: Record<string, string> = {
  chunk: 'Chunking',
  embed: 'Embedding',
  cluster: 'Clustering',
}

function PipelineProgress({ phases, error }: { phases: PhaseProgress[]; error?: string }) {
  return (
    <div style={{ marginTop: 8, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {phases.map(p => (
        <div key={p.phase} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ width: 14, textAlign: 'center', color: p.status === 'done' ? '#2e7d32' : p.status === 'error' ? '#c00' : p.status === 'running' ? '#6b7de0' : '#bbb' }}>
            {p.status === 'done' ? '✓' : p.status === 'error' ? '✗' : p.status === 'running' ? '…' : '·'}
          </span>
          <span style={{ color: p.status === 'waiting' ? '#aaa' : '#333', minWidth: 80 }}>
            {PHASE_LABELS[p.phase] ?? p.phase}
          </span>
          {p.items !== undefined && (
            <span style={{ color: '#888' }}>{p.items} item{p.items !== 1 ? 's' : ''}</span>
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
  const [showStorage, setShowStorage] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showPluginIngest, setShowPluginIngest] = useState(false)
  const [detailWorkRef, setDetailWorkRef] = useState<string | number | null>(null)
  const [lastIngest, setLastIngest] = useState<IngestResult | null>(null)
  const [lastIngestError, setLastIngestError] = useState<string | null>(null)
  const [lastPluginIngest, setLastPluginIngest] = useState<IngestResult | null>(null)
  const [updateResult, setUpdateResult] = useState<{ updated: number; unchanged: number } | null>(null)
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

  const ingest = useMutation({
    mutationFn: (paths: string[]) => api.works.ingest(projectId!, paths),
    onSuccess: (result) => {
      setLastIngest(result)
      setLastIngestError(null)
      qc.invalidateQueries({ queryKey: ['works', projectId] })
      if (result.added + result.updated > 0) setShowStorage(false)
    },
    onError: (e) => setLastIngestError(e instanceof Error ? e.message : String(e)),
  })

  const removeWork = useMutation({
    mutationFn: (ref: string) => api.works.delete(projectId!, ref),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['works', projectId] })
      qc.invalidateQueries({ queryKey: ['ratings', projectId] })
    },
  })

  const updatePlugin = useMutation({
    mutationFn: () => api.works.updatePlugin(projectId!),
    onSuccess: (result) => {
      setUpdateResult(result)
      qc.invalidateQueries({ queryKey: ['works', projectId] })
    },
  })

  const runPipeline = async () => {
    setPipelineRunning(true)
    setPipelineError(null)
    setPhaseProgress(PHASES.map(p => ({ phase: p, status: 'waiting' })))
    try {
      await api.pipeline.runStream(projectId!, (event: PipelineStreamEvent) => {
        if ('phase' in event) {
          setPhaseProgress(prev => prev.map(p =>
            p.phase === event.phase
              ? { ...p, status: event.status as PhaseStatus, items: 'items_processed' in event ? event.items_processed : p.items }
              : p
          ))
          if (event.status === 'error') setPipelineError(event.error)
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

  const pipelineDone = phaseProgress.length > 0 && !pipelineRunning && !pipelineError

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <Link to="/">← Projects</Link>
          <h2 style={{ margin: '8px 0 4px' }}>{project.name}</h2>
          {project.description && <p style={{ margin: 0, color: '#666' }}>{project.description}</p>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link to={`/projects/${projectId}/rate`}><button>Rate Chunks</button></Link>
          <Link to={`/projects/${projectId}/profile`}><button>Profile</button></Link>
          <button onClick={() => setShowSettings(true)}>Settings</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{works?.length ?? 0}</div>
          <div style={{ color: '#666' }}>Works</div>
        </div>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{ratings?.filter(r => !r.skipped).length ?? 0}</div>
          <div style={{ color: '#666' }}>Ratings</div>
        </div>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{project.crystallisation_threshold}</div>
          <div style={{ color: '#666' }}>Threshold</div>
        </div>
      </div>

      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button
          onClick={() => { setLastIngest(null); setLastIngestError(null); setShowStorage(true) }}
          style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
        >
          Browse &amp; Ingest Files
        </button>
        <button
          onClick={() => { setLastPluginIngest(null); setShowPluginIngest(true) }}
          style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
        >
          Plugin Ingest
        </button>
        <button
          onClick={() => { setUpdateResult(null); updatePlugin.mutate() }}
          disabled={updatePlugin.isPending}
          style={{ padding: '8px 18px', background: 'none', border: '1px solid #6b7de0', color: '#6b7de0', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
        >
          {updatePlugin.isPending ? 'Updating…' : 'Update from Plugin'}
        </button>
        {lastIngest && (
          <span style={{ fontSize: 13, color: '#390' }}>
            Added {lastIngest.added}, updated {lastIngest.updated}, unchanged {lastIngest.skipped}
          </span>
        )}
        {lastPluginIngest && (
          <span style={{ fontSize: 13, color: '#390' }}>
            Plugin: added {lastPluginIngest.added}, updated {lastPluginIngest.updated}, unchanged {lastPluginIngest.skipped}
          </span>
        )}
        {updateResult && (
          <span style={{ fontSize: 13, color: '#390' }}>
            Updated {updateResult.updated}, unchanged {updateResult.unchanged}
          </span>
        )}
        {updatePlugin.error && (
          <span style={{ fontSize: 13, color: '#c00' }}>{(updatePlugin.error as any)?.message ?? 'Update failed'}</span>
        )}
        {ingest.error && (
          <span style={{ fontSize: 13, color: '#c00' }}>{String(ingest.error)}</span>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Works</h3>
        <button onClick={runPipeline} disabled={pipelineRunning}>
          {pipelineRunning ? 'Running…' : 'Run Pipeline'}
        </button>
      </div>

      {phaseProgress.length > 0 && (
        <PipelineProgress
          phases={phaseProgress}
          error={pipelineError ?? undefined}
        />
      )}
      {pipelineDone && (
        <p style={{ color: '#390', fontSize: 13, marginTop: 8 }}>
          Pipeline complete — {phaseProgress.reduce((n, p) => n + (p.items ?? 0), 0)} items processed
        </p>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 12 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #e0e0e0', textAlign: 'left' }}>
            <th style={{ padding: '4px 8px' }}>#</th>
            <th style={{ padding: '4px 8px' }}>File</th>
            <th style={{ padding: '4px 8px' }}>Phase</th>
            <th style={{ padding: '4px 8px' }}>Ingested</th>
            <th style={{ padding: '4px 8px' }}></th>
            <th style={{ padding: '4px 8px' }}></th>
          </tr>
        </thead>
        <tbody>
          {works?.map(w => (
            <tr key={w.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
              <td style={{ padding: '4px 8px', color: '#888' }}>#{w.project_seq}</td>
              <td style={{ padding: '4px 8px' }}>
                {w.work_title ?? w.source_path?.split('/').pop() ?? w.id}
              </td>
              <td style={{ padding: '4px 8px' }}>
                <span style={{
                  background: w.pipeline_phase === 'clustered' ? '#e8f5e9' : '#fff8e1',
                  padding: '2px 6px', borderRadius: 4, fontSize: 11,
                }}>
                  {w.pipeline_phase}
                </span>
              </td>
              <td style={{ padding: '4px 8px', color: '#888' }}>{w.ingested_at.slice(0, 10)}</td>
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

      {showStorage && (
        <StorageBrowser
          onIngest={paths => ingest.mutate(paths)}
          ingesting={ingest.isPending}
          ingestResult={lastIngest}
          ingestError={lastIngestError}
          onClose={() => { setShowStorage(false); setLastIngest(null); setLastIngestError(null) }}
        />
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
          onClose={() => setShowPluginIngest(false)}
          onSuccess={(result) => {
            setLastPluginIngest(result)
            qc.invalidateQueries({ queryKey: ['works', projectId] })
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
    </div>
  )
}

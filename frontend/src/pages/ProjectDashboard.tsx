import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import StorageBrowser from '../components/StorageBrowser'
import type { IngestResult } from '../api/types'

export default function ProjectDashboard() {
  const { projectId } = useParams<{ projectId: string }>()!
  const qc = useQueryClient()
  const [showStorage, setShowStorage] = useState(false)
  const [lastIngest, setLastIngest] = useState<IngestResult | null>(null)

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
      qc.invalidateQueries({ queryKey: ['works', projectId] })
      setShowStorage(false)
    },
  })

  const runPipeline = useMutation({
    mutationFn: () => api.pipeline.run(projectId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['works', projectId] }),
  })

  const removeWork = useMutation({
    mutationFn: (ref: string) => api.works.delete(projectId!, ref),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['works', projectId] }),
  })

  if (isLoading || !project) return <p>Loading…</p>

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
        </div>
      </div>

      <div style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{works?.length ?? 0}</div>
          <div style={{ color: '#666' }}>Works</div>
        </div>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{ratings?.length ?? 0}</div>
          <div style={{ color: '#666' }}>Ratings</div>
        </div>
        <div style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16, flex: 1 }}>
          <div style={{ fontSize: 28, fontWeight: 700 }}>{project.crystallisation_threshold}</div>
          <div style={{ color: '#666' }}>Threshold</div>
        </div>
      </div>

      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={() => { setLastIngest(null); setShowStorage(true) }}
          style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
        >
          Browse &amp; Ingest Files
        </button>
        {lastIngest && (
          <span style={{ fontSize: 13, color: '#390' }}>
            Added {lastIngest.added}, updated {lastIngest.updated}, unchanged {lastIngest.skipped}
          </span>
        )}
        {ingest.error && (
          <span style={{ fontSize: 13, color: '#c00' }}>{String(ingest.error)}</span>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Works</h3>
        <button onClick={() => runPipeline.mutate()} disabled={runPipeline.isPending}>
          {runPipeline.isPending ? 'Running pipeline…' : 'Run Pipeline'}
        </button>
      </div>
      {runPipeline.data && (
        <p style={{ color: '#390', fontSize: 13 }}>
          Pipeline complete — {runPipeline.data.total_processed} items processed
        </p>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #e0e0e0', textAlign: 'left' }}>
            <th style={{ padding: '4px 8px' }}>#</th>
            <th style={{ padding: '4px 8px' }}>File</th>
            <th style={{ padding: '4px 8px' }}>Phase</th>
            <th style={{ padding: '4px 8px' }}>Ingested</th>
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
                  onClick={() => confirm('Remove this work?') && removeWork.mutate(String(w.project_seq))}
                  style={{ color: '#c00', fontSize: 11 }}
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
          onClose={() => setShowStorage(false)}
        />
      )}
    </div>
  )
}

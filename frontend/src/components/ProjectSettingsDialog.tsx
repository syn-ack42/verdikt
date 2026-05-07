import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import DimensionEditor from './DimensionEditor'
import type { Project, RatingDimension } from '../api/types'

interface Props {
  project: Project
  onClose: () => void
}

export default function ProjectSettingsDialog({ project, onClose }: Props) {
  const { data: ratings } = useQuery({
    queryKey: ['ratings', project.id],
    queryFn: () => api.ratings.list(project.id),
  })
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [threshold, setThreshold] = useState(project.crystallisation_threshold)
  const [chunkMin, setChunkMin] = useState(project.chunk_min_size)
  const [chunkMax, setChunkMax] = useState(project.chunk_max_size)
  const [dims, setDims] = useState<RatingDimension[]>(project.rating_dimensions)
  const [llmModel, setLlmModel] = useState(project.llm_model ?? '')
  const [embModel, setEmbModel] = useState(project.embedding_model ?? '')
  const [embChanged, setEmbChanged] = useState(false)

  const isImage = project.domain === 'image'

  const originalNames = project.rating_dimensions.map(d => d.name)
  const originalDescriptions = project.rating_dimensions.map(d => d.description)
  const ratedNames = new Set((ratings ?? []).flatMap(r => Object.keys(r.dimension_scores)))

  const { data: modelDefaults } = useQuery({
    queryKey: ['model-defaults'],
    queryFn: () => api.models.defaults(),
  })
  const { data: projectDefaults } = useQuery({
    queryKey: ['projects', 'defaults'],
    queryFn: () => api.projects.defaults(),
  })

  const rangeMin = projectDefaults?.chunk_size_min_lower ?? 0
  const rangeMax = projectDefaults?.chunk_size_max_upper ?? 1000
  const { data: llmModels } = useQuery({
    queryKey: ['models', 'llm', project.domain],
    queryFn: () => api.models.list('llm', project.domain),
  })
  const { data: embModels } = useQuery({
    queryKey: ['models', 'embedding', project.domain],
    queryFn: () => api.models.list('embedding', project.domain),
    enabled: !isImage,
  })

  const defaultLlm = modelDefaults?.llm_by_domain?.[project.domain] ?? null

  const deleteProject = useMutation({
    mutationFn: () => api.projects.delete(project.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate('/')
    },
  })

  const save = useMutation({
    mutationFn: () => {
      const renames: Record<string, string> = {}
      dims.forEach((d, i) => {
        const orig = originalNames[i]
        if (orig && d.name !== orig) renames[orig] = d.name
      })
      return api.projects.update(project.id, {
        name,
        description: description || undefined,
        rating_dimensions: dims,
        crystallisation_threshold: threshold,
        ...(isImage ? {} : { chunk_min_size: chunkMin, chunk_max_size: chunkMax }),
        llm_model: llmModel || undefined,
        embedding_model: embModel || undefined,
        ...(Object.keys(renames).length > 0 ? { dimension_renames: renames } : {}),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects', project.id] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      onClose()
    },
  })

  const inputStyle: React.CSSProperties = {
    width: '100%',
    background: 'var(--bg)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '6px 8px',
    boxSizing: 'border-box',
    fontSize: 14,
  }

  const defaultEmbLabel = modelDefaults ? ' (bundled)' : ''

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)', color: 'var(--text)',
        borderRadius: 10, width: 'min(680px, 94vw)', maxHeight: '85vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Project Settings</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)', lineHeight: 1 }}>×</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          <form id="settings-form" onSubmit={e => { e.preventDefault(); save.mutate() }}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Name</label>
              <input required value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Description</label>
              <input value={description} onChange={e => setDescription(e.target.value)} style={inputStyle} />
            </div>

            <div style={{ marginBottom: 16, display: 'flex', gap: 24 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Crystallisation threshold</label>
                <input
                  type="number" min={1} value={threshold}
                  onChange={e => setThreshold(Number(e.target.value))}
                  style={{ ...inputStyle, width: 100 }}
                />
              </div>
              {!isImage && (
                <div>
                  <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Chunk size (min / max words)</label>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input
                      type="number" min={rangeMin} max={rangeMax} value={chunkMin}
                      onChange={e => setChunkMin(Number(e.target.value))}
                      style={{ ...inputStyle, width: 80 }}
                    />
                    <span style={{ color: 'var(--text-muted)' }}>–</span>
                    <input
                      type="number" min={rangeMin} max={rangeMax} value={chunkMax}
                      onChange={e => setChunkMax(Number(e.target.value))}
                      style={{ ...inputStyle, width: 80 }}
                    />
                  </div>
                </div>
              )}
            </div>

            <div style={{ marginBottom: 16, display: 'flex', gap: 16 }}>
              <div style={{ flex: 1 }}>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Language model</label>
                {(llmModels ?? []).length > 0 ? (
                  <select
                    value={llmModel || (defaultLlm ?? '')}
                    onChange={e => setLlmModel(e.target.value)}
                    style={{ ...inputStyle }}
                  >
                    {(llmModels ?? []).map(m => (
                      <option key={m.id} value={m.id}>{m.display_name || m.id}{m.parameter_size ? ` · ${m.parameter_size}` : ''}{m.is_default ? ' ★' : ''}</option>
                    ))}
                  </select>
                ) : (
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>No models enabled for this domain.</p>
                )}
              </div>
              {!isImage && (
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Embedding model</label>
                  <select
                    value={embModel}
                    onChange={e => {
                      setEmbModel(e.target.value)
                      setEmbChanged(e.target.value !== (project.embedding_model ?? ''))
                    }}
                    style={{ ...inputStyle }}
                  >
                    <option value="">Bundled default{defaultEmbLabel}</option>
                    {(embModels ?? []).map(m => (
                      <option key={m.id} value={m.id}>{m.display_name || m.id}</option>
                    ))}
                  </select>
                  {embChanged && (
                    <p style={{ margin: '6px 0 0', fontSize: 12, color: '#c08020' }}>
                      Changing the embedding model invalidates existing vectors. Re-run the pipeline after saving to re-embed all works.
                    </p>
                  )}
                </div>
              )}
            </div>

            <div style={{ marginBottom: 8 }}>
              <label style={{ display: 'block', marginBottom: 8, fontSize: 13, fontWeight: 600 }}>Rating Dimensions</label>
              <DimensionEditor
                dimensions={dims}
                onChange={setDims}
                originalNames={originalNames}
                originalDescriptions={originalDescriptions}
                ratedNames={ratedNames}
              />
            </div>
          </form>

          <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <p style={{ margin: '0 0 10px', fontSize: 13, fontWeight: 600, color: '#c00' }}>Danger zone</p>
            <button
              type="button"
              onClick={() => confirm(`Permanently delete "${project.name}" and all its data?`) && deleteProject.mutate()}
              disabled={deleteProject.isPending}
              style={{ padding: '6px 14px', border: '1px solid #c00', borderRadius: 4, color: '#c00', background: 'none', cursor: 'pointer', fontSize: 13 }}
            >
              {deleteProject.isPending ? 'Deleting…' : 'Delete project'}
            </button>
          </div>
        </div>

        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {save.error && (
            <span style={{ fontSize: 13, color: '#c00' }}>{String(save.error)}</span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button type="button" onClick={onClose} style={{ padding: '6px 14px' }}>Cancel</button>
            <button
              type="submit" form="settings-form" disabled={save.isPending}
              style={{ padding: '6px 16px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

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

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg)',
  color: 'var(--text)',
  fontSize: 14,
  boxSizing: 'border-box',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  marginBottom: 6,
  color: 'var(--text-muted)',
}

const fieldStyle: React.CSSProperties = {
  marginBottom: 20,
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
  const defaultEmbLabel = modelDefaults ? ' (bundled)' : ''

  const selectedLlmModel = (llmModels ?? []).find(m => m.id === (llmModel || defaultLlm))
  const selectedEmbModel = (embModels ?? []).find(m => m.id === embModel)
  const selectedLlmIsVenice = selectedLlmModel?.source === 'venice'
  const selectedEmbIsVenice = selectedEmbModel?.source === 'venice'

  const _fmtCost = (input?: number | null, output?: number | null) => {
    if (input == null && output == null) return null
    return `$${input?.toFixed(2) ?? '?'} in / $${output?.toFixed(2) ?? '?'} out per million tokens`
  }
  const llmCostLabel = _fmtCost(selectedLlmModel?.input_cost_usd_per_mtok, selectedLlmModel?.output_cost_usd_per_mtok)
  const embCostLabel = _fmtCost(selectedEmbModel?.input_cost_usd_per_mtok, selectedEmbModel?.output_cost_usd_per_mtok)

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

  return (
    <div
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)',
        color: 'var(--text)',
        borderRadius: 10,
        width: 'min(680px, 94vw)',
        maxHeight: '88vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Project Settings</h3>
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>{project.name}</p>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)', lineHeight: 1, padding: '4px 6px' }}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          <form id="settings-form" onSubmit={e => { e.preventDefault(); save.mutate() }}>

            <div style={fieldStyle}>
              <label style={labelStyle}>Name</label>
              <input required value={name} onChange={e => setName(e.target.value)} style={inputStyle} />
            </div>

            <div style={fieldStyle}>
              <label style={labelStyle}>Description</label>
              <input value={description} onChange={e => setDescription(e.target.value)} style={inputStyle} placeholder="Optional" />
            </div>

            {/* Numeric settings */}
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 20 }}>
              <div>
                <label style={labelStyle}>Crystallisation threshold</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="number" min={1} value={threshold}
                    onChange={e => setThreshold(Number(e.target.value))}
                    style={{ ...inputStyle, width: 80 }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>ratings</span>
                </div>
              </div>
              {!isImage && (
                <div>
                  <label style={labelStyle}>Chunk size</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <input
                      type="number" min={rangeMin} max={rangeMax} value={chunkMin}
                      onChange={e => setChunkMin(Number(e.target.value))}
                      style={{ ...inputStyle, width: 80 }}
                    />
                    <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>–</span>
                    <input
                      type="number" min={rangeMin} max={rangeMax} value={chunkMax}
                      onChange={e => setChunkMax(Number(e.target.value))}
                      style={{ ...inputStyle, width: 80 }}
                    />
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>words</span>
                  </div>
                </div>
              )}
            </div>

            {/* Models */}
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
              <div style={{ flex: 1, minWidth: 180 }}>
                <label style={labelStyle}>Language model</label>
                {(llmModels ?? []).length > 0 ? (
                  <select
                    value={llmModel || (defaultLlm ?? '')}
                    onChange={e => setLlmModel(e.target.value)}
                    style={inputStyle}
                  >
                    {(llmModels ?? []).map(m => (
                      <option key={m.id} value={m.id}>
                        {m.source === 'venice' ? '[Venice] ' : ''}{m.display_name || m.id}{m.parameter_size ? ` · ${m.parameter_size}` : ''}{m.is_default ? ' ★' : ''}
                      </option>
                    ))}
                  </select>
                ) : (
                  <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>No models enabled for this domain.</p>
                )}
                {selectedLlmIsVenice && (
                  <p style={{ margin: '6px 0 0', fontSize: 12, color: '#7c3aed', lineHeight: 1.4 }}>
                    Venice.ai — API costs apply.{llmCostLabel ? ` ${llmCostLabel}.` : ''}
                    {selectedLlmModel?.privacy === 'private' && ' Prompts are not logged.'}
                    {selectedLlmModel?.privacy === 'anonymized' && ' Prompts may be retained anonymized.'}
                  </p>
                )}
              </div>
              {!isImage && (
                <div style={{ flex: 1, minWidth: 180 }}>
                  <label style={labelStyle}>Embedding model</label>
                  <select
                    value={embModel}
                    onChange={e => {
                      setEmbModel(e.target.value)
                      setEmbChanged(e.target.value !== (project.embedding_model ?? ''))
                    }}
                    style={inputStyle}
                  >
                    <option value="">Bundled default{defaultEmbLabel}</option>
                    {(embModels ?? []).map(m => (
                      <option key={m.id} value={m.id}>{m.source === 'venice' ? '[Venice] ' : ''}{m.display_name || m.id}</option>
                    ))}
                  </select>
                  {embChanged && (
                    <p style={{ margin: '6px 0 0', fontSize: 12, color: '#b45309', lineHeight: 1.4 }}>
                      Changing the embedding model invalidates existing vectors — re-run the pipeline after saving.
                    </p>
                  )}
                  {selectedEmbIsVenice && (
                    <p style={{ margin: '6px 0 0', fontSize: 12, color: '#7c3aed', lineHeight: 1.4 }}>
                      Venice.ai — API costs apply.{embCostLabel ? ` ${embCostLabel}.` : ''}
                      {selectedEmbModel?.privacy === 'private' && ' Prompts are not logged.'}
                      {selectedEmbModel?.privacy === 'anonymized' && ' Prompts may be retained anonymized.'}
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Dimensions */}
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Rating Dimensions</label>
              <DimensionEditor
                dimensions={dims}
                onChange={setDims}
                originalNames={originalNames}
                originalDescriptions={originalDescriptions}
                ratedNames={ratedNames}
              />
            </div>
          </form>

          {/* Danger zone */}
          <div style={{ marginTop: 28, padding: '16px', borderRadius: 7, border: '1px solid rgba(200,0,0,0.2)', background: 'rgba(200,0,0,0.04)' }}>
            <p style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 700, color: '#c00' }}>Danger zone</p>
            <button
              type="button"
              onClick={() => confirm(`Permanently delete "${project.name}" and all its data?`) && deleteProject.mutate()}
              disabled={deleteProject.isPending}
              style={{
                padding: '7px 16px',
                border: '1px solid #c00',
                borderRadius: 6,
                color: '#c00',
                background: 'none',
                cursor: deleteProject.isPending ? 'default' : 'pointer',
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              {deleteProject.isPending ? 'Deleting…' : 'Delete project'}
            </button>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 20px',
          borderTop: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
          gap: 8,
        }}>
          <div style={{ flex: 1 }}>
            {save.error && (
              <span style={{ fontSize: 13, color: '#c00' }}>{String(save.error)}</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '8px 18px',
                background: 'none',
                border: '1px solid var(--border)',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              form="settings-form"
              disabled={save.isPending}
              style={{
                padding: '8px 20px',
                background: '#6b7de0',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: save.isPending ? 'default' : 'pointer',
                fontSize: 14,
                fontWeight: 600,
                opacity: save.isPending ? 0.7 : 1,
              }}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

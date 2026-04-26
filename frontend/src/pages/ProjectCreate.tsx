import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import DimensionEditor from '../components/DimensionEditor'
import type { ModelCatalogEntry, RatingDimension } from '../api/types'

const DEFAULT_DIMS: RatingDimension[] = [
  { name: 'Prose Quality', description: 'Clarity, style and craft of the writing', weight: 1.0 },
  { name: 'Pacing', description: 'Narrative flow and engagement', weight: 1.0 },
  { name: 'Atmosphere', description: 'World-building, setting and mood', weight: 1.0 },
  { name: 'Character', description: 'Depth and authenticity of characterisation', weight: 1.0 },
  { name: 'Originality', description: 'Freshness of ideas and subversion of expectations', weight: 1.0 },
]

function modelOption(m: ModelCatalogEntry): string {
  const parts: string[] = []
  if (m.parameter_size) parts.push(m.parameter_size)
  if (m.context_length) parts.push(`${(m.context_length / 1000).toFixed(0)}k ctx`)
  return parts.length ? `${m.display_name} (${parts.join(', ')})` : m.display_name
}

export default function ProjectCreate() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [threshold, setThreshold] = useState(50)
  const [dims, setDims] = useState<RatingDimension[]>(DEFAULT_DIMS)
  const [llmModel, setLlmModel] = useState<string>('')
  const [embModel, setEmbModel] = useState<string>('')

  const { data: llmModels } = useQuery({
    queryKey: ['models', 'llm'],
    queryFn: () => api.models.list('llm'),
  })
  const { data: embModels } = useQuery({
    queryKey: ['models', 'embedding', 'text'],
    queryFn: () => api.models.list('embedding', 'text'),
  })

  const create = useMutation({
    mutationFn: () => api.projects.create({
      name,
      description: description || undefined,
      domain: 'text',
      rating_dimensions: dims,
      crystallisation_threshold: threshold,
      llm_model: llmModel || undefined,
      embedding_model: embModel || undefined,
    }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${p.id}`)
    },
  })

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <h2>New Project</h2>
      <form onSubmit={e => { e.preventDefault(); create.mutate() }}>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 4 }}>Name</label>
          <input
            required
            value={name}
            onChange={e => setName(e.target.value)}
            style={{ width: '100%' }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 4 }}>Description (optional)</label>
          <input
            value={description}
            onChange={e => setDescription(e.target.value)}
            style={{ width: '100%' }}
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 4 }}>
            Crystallisation threshold (ratings needed)
          </label>
          <input
            type="number"
            min={1}
            value={threshold}
            onChange={e => setThreshold(Number(e.target.value))}
            style={{ width: '5ch' }}
          />
        </div>
        {llmModels && llmModels.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 4 }}>Language model <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: 12 }}>(optional — uses server default if not set)</span></label>
            <select value={llmModel} onChange={e => setLlmModel(e.target.value)} style={{ width: '100%' }}>
              <option value="">Server default</option>
              {llmModels.map(m => (
                <option key={m.id} value={m.id} title={m.description}>{modelOption(m)}</option>
              ))}
            </select>
          </div>
        )}
        {embModels && embModels.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 4 }}>Embedding model <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: 12 }}>(cannot be changed after embedding)</span></label>
            <select value={embModel} onChange={e => setEmbModel(e.target.value)} style={{ width: '100%' }}>
              <option value="">Server default</option>
              {embModels.map(m => (
                <option key={m.id} value={m.id} title={m.description}>{modelOption(m)}</option>
              ))}
            </select>
          </div>
        )}
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: 'block', marginBottom: 8 }}>Rating Dimensions</label>
          <DimensionEditor dimensions={dims} onChange={setDims} />
        </div>
        {create.error && (
          <p style={{ color: '#c00' }}>{String(create.error)}</p>
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="submit" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create Project'}
          </button>
          <button type="button" onClick={() => navigate('/')}>Cancel</button>
        </div>
      </form>
    </div>
  )
}

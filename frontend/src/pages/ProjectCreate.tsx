import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import DimensionEditor from '../components/DimensionEditor'
import type { ModelCatalogEntry, RatingDimension } from '../api/types'

type Domain = 'text' | 'image'

const DOMAIN_OPTIONS: { value: Domain; label: string; description: string }[] = [
  { value: 'text', label: 'Text', description: 'Prose, articles, stories, documents' },
  { value: 'image', label: 'Image', description: 'Photos, illustrations, artwork' },
]

const DEFAULT_DIMS: Record<Domain, RatingDimension[]> = {
  text: [
    { name: 'Prose Quality', description: 'Clarity, style and craft of the writing', weight: 1.0 },
    { name: 'Pacing', description: 'Narrative flow and engagement', weight: 1.0 },
    { name: 'Atmosphere', description: 'World-building, setting and mood', weight: 1.0 },
    { name: 'Character', description: 'Depth and authenticity of characterisation', weight: 1.0 },
    { name: 'Originality', description: 'Freshness of ideas and subversion of expectations', weight: 1.0 },
  ],
  image: [
    { name: 'Composition', description: 'Balance, framing and use of space', weight: 1.0 },
    { name: 'Lighting', description: 'Quality and mood of light', weight: 1.0 },
    { name: 'Colour', description: 'Palette harmony and emotional impact', weight: 1.0 },
    { name: 'Subject', description: 'Clarity and interest of the subject matter', weight: 1.0 },
    { name: 'Originality', description: 'Freshness and distinctiveness of the image', weight: 1.0 },
  ],
}

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
  const [domain, setDomain] = useState<Domain>('text')
  const [threshold, setThreshold] = useState<number | null>(null)
  const [chunkMin, setChunkMin] = useState<number | null>(null)
  const [chunkMax, setChunkMax] = useState<number | null>(null)
  const [dims, setDims] = useState<RatingDimension[]>(DEFAULT_DIMS.text)
  const [llmModel, setLlmModel] = useState<string>('')
  const [embModel, setEmbModel] = useState<string>('')

  function handleDomainChange(d: Domain) {
    setDomain(d)
    setDims(DEFAULT_DIMS[d])
    setEmbModel('')
    setLlmModel('')
  }

  const { data: projectDefaults } = useQuery({
    queryKey: ['projects', 'defaults'],
    queryFn: () => api.projects.defaults(),
  })

  useEffect(() => {
    if (projectDefaults && threshold === null) {
      setThreshold(projectDefaults.default_crystallisation_threshold)
      setChunkMin(projectDefaults.default_chunk_min_size)
      setChunkMax(projectDefaults.default_chunk_max_size)
    }
  }, [projectDefaults, threshold])

  const { data: domainAvailability } = useQuery({
    queryKey: ['models', 'domain-availability'],
    queryFn: () => api.models.domainAvailability(),
  })
  const { data: modelDefaults } = useQuery({
    queryKey: ['models', 'defaults'],
    queryFn: () => api.models.defaults(),
  })
  const { data: llmModels } = useQuery({
    queryKey: ['models', 'llm', domain],
    queryFn: () => api.models.list('llm', domain),
  })
  const { data: embModels } = useQuery({
    queryKey: ['models', 'embedding', domain],
    queryFn: () => api.models.list('embedding', domain),
  })

  const defaultLlm = modelDefaults?.llm_by_domain?.[domain] ?? null

  const rangeMin = projectDefaults?.chunk_size_min_lower ?? 0
  const rangeMax = projectDefaults?.chunk_size_max_upper ?? 1000

  const create = useMutation({
    mutationFn: () => api.projects.create({
      name,
      description: description || undefined,
      domain,
      rating_dimensions: dims,
      crystallisation_threshold: threshold ?? projectDefaults?.default_crystallisation_threshold,
      ...(domain !== 'image' ? {
        chunk_min_size: chunkMin ?? projectDefaults?.default_chunk_min_size,
        chunk_max_size: chunkMax ?? projectDefaults?.default_chunk_max_size,
      } : {}),
      llm_model: llmModel || defaultLlm || undefined,
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
          <label style={{ display: 'block', marginBottom: 8 }}>Domain</label>
          <div style={{ display: 'flex', gap: 8 }}>
            {DOMAIN_OPTIONS.map(opt => {
              const available = domainAvailability == null || domainAvailability[opt.value] !== false
              return (
                <button
                  key={opt.value}
                  type="button"
                  title={available ? opt.description : 'No LLM model enabled for this domain — configure in Admin › Models'}
                  disabled={!available}
                  onClick={() => handleDomainChange(opt.value)}
                  style={{
                    flex: 1, padding: '8px 12px', borderRadius: 6, fontSize: 14,
                    cursor: available ? 'pointer' : 'not-allowed',
                    border: domain === opt.value ? '2px solid #6b7de0' : '1px solid var(--border)',
                    background: domain === opt.value ? 'rgba(107,125,224,0.12)' : 'none',
                    color: domain === opt.value ? '#6b7de0' : available ? 'var(--text)' : 'var(--text-muted)',
                    fontWeight: domain === opt.value ? 600 : 400,
                    opacity: available ? 1 : 0.5,
                  }}
                >
                  {opt.label}{!available && ' (no model)'}
                </button>
              )
            })}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
            {DOMAIN_OPTIONS.find(o => o.value === domain)?.description}
          </div>
        </div>

        <div style={{ marginBottom: 16, display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <label style={{ display: 'block', marginBottom: 4 }}>
              Crystallisation threshold (ratings needed)
            </label>
            <input
              type="number"
              min={1}
              value={threshold ?? ''}
              onChange={e => setThreshold(Number(e.target.value))}
              style={{ width: '6ch' }}
            />
          </div>
          {domain !== 'image' && (
            <div>
              <label style={{ display: 'block', marginBottom: 4 }}>Chunk size (min / max words)</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="number"
                  min={rangeMin}
                  max={rangeMax}
                  value={chunkMin ?? ''}
                  onChange={e => setChunkMin(Number(e.target.value))}
                  style={{ width: '6ch' }}
                />
                <span style={{ color: 'var(--text-muted)' }}>–</span>
                <input
                  type="number"
                  min={rangeMin}
                  max={rangeMax}
                  value={chunkMax ?? ''}
                  onChange={e => setChunkMax(Number(e.target.value))}
                  style={{ width: '6ch' }}
                />
              </div>
            </div>
          )}
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 4 }}>Language model</label>
          {llmModels && llmModels.length > 0 ? (
            <select
              value={llmModel || (defaultLlm ?? '')}
              onChange={e => setLlmModel(e.target.value)}
              style={{ width: '100%' }}
            >
              {llmModels.map(m => (
                <option key={m.id} value={m.id} title={m.description}>
                  {modelOption(m)}{m.is_default ? ' ★' : ''}
                </option>
              ))}
            </select>
          ) : (
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
              No LLM models enabled for this domain. Go to Admin › Models to enable one.
            </p>
          )}
        </div>
        {embModels && embModels.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 4 }}>Embedding model <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: 12 }}>(cannot be changed after embedding)</span></label>
            <select value={embModel} onChange={e => setEmbModel(e.target.value)} style={{ width: '100%' }}>
              <option value="">Bundled default</option>
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

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
    <div style={{ maxWidth: 680, margin: '0 auto', padding: 'clamp(16px, 4vw, 32px) clamp(12px, 4vw, 24px)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
        <button
          type="button"
          onClick={() => navigate('/')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 14, padding: 0, flexShrink: 0 }}
        >
          ← Projects
        </button>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>New Project</h1>
      </div>

      <form onSubmit={e => { e.preventDefault(); create.mutate() }}>
        {/* Name */}
        <div style={fieldStyle}>
          <label style={labelStyle}>Name</label>
          <input
            required
            value={name}
            onChange={e => setName(e.target.value)}
            style={inputStyle}
            placeholder="My project"
          />
        </div>

        {/* Description */}
        <div style={fieldStyle}>
          <label style={labelStyle}>
            Description <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(optional)</span>
          </label>
          <input
            value={description}
            onChange={e => setDescription(e.target.value)}
            style={inputStyle}
            placeholder="What is this project about?"
          />
        </div>

        {/* Domain */}
        <div style={fieldStyle}>
          <label style={labelStyle}>Domain</label>
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
                    flex: 1,
                    padding: '10px 12px',
                    borderRadius: 6,
                    fontSize: 14,
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
          <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            {DOMAIN_OPTIONS.find(o => o.value === domain)?.description}
          </p>
        </div>

        {/* Rating Dimensions */}
        <div style={{ ...fieldStyle, marginBottom: 28 }}>
          <label style={labelStyle}>Rating Dimensions</label>
          <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--text-muted)' }}>
            Define what matters when rating content. You can start with the defaults and refine later, or use{' '}
            <em>Discover</em> to let Verdikt suggest dimensions from your reactions.
          </p>
          <DimensionEditor dimensions={dims} onChange={setDims} />
        </div>

        {/* Advanced settings */}
        <div style={{ paddingTop: 20, borderTop: '1px solid var(--border)', marginBottom: 28 }}>
          <p style={{ margin: '0 0 20px', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
            Advanced
          </p>

          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 20 }}>
            <div>
              <label style={labelStyle}>Crystallisation threshold</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="number"
                  min={1}
                  value={threshold ?? ''}
                  onChange={e => setThreshold(Number(e.target.value))}
                  style={{ ...inputStyle, width: 80 }}
                />
                <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>ratings to build first profile</span>
              </div>
            </div>
            {domain !== 'image' && (
              <div>
                <label style={labelStyle}>Chunk size</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="number"
                    min={rangeMin}
                    max={rangeMax}
                    value={chunkMin ?? ''}
                    onChange={e => setChunkMin(Number(e.target.value))}
                    style={{ ...inputStyle, width: 80 }}
                  />
                  <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>–</span>
                  <input
                    type="number"
                    min={rangeMin}
                    max={rangeMax}
                    value={chunkMax ?? ''}
                    onChange={e => setChunkMax(Number(e.target.value))}
                    style={{ ...inputStyle, width: 80 }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>words</span>
                </div>
              </div>
            )}
          </div>

          <div style={fieldStyle}>
            <label style={labelStyle}>Language model</label>
            {llmModels && llmModels.length > 0 ? (
              <select
                value={llmModel || (defaultLlm ?? '')}
                onChange={e => setLlmModel(e.target.value)}
                style={inputStyle}
              >
                {llmModels.map(m => (
                  <option key={m.id} value={m.id} title={m.description}>
                    {modelOption(m)}{m.is_default ? ' ★' : ''}
                  </option>
                ))}
              </select>
            ) : (
              <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
                No LLM models enabled for this domain — go to Admin › Models to enable one.
              </p>
            )}
          </div>

          {embModels && embModels.length > 0 && (
            <div style={fieldStyle}>
              <label style={labelStyle}>
                Embedding model{' '}
                <span style={{ fontWeight: 400, fontSize: 12 }}>(cannot be changed after first embedding)</span>
              </label>
              <select value={embModel} onChange={e => setEmbModel(e.target.value)} style={inputStyle}>
                <option value="">Bundled default</option>
                {embModels.map(m => (
                  <option key={m.id} value={m.id} title={m.description}>{modelOption(m)}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {create.error && (
          <p style={{ margin: '0 0 16px', fontSize: 13, color: '#c00' }}>{String(create.error)}</p>
        )}

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="submit"
            disabled={create.isPending}
            style={{
              padding: '10px 24px',
              background: '#6b7de0',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: create.isPending ? 'default' : 'pointer',
              fontSize: 14,
              fontWeight: 600,
              opacity: create.isPending ? 0.7 : 1,
            }}
          >
            {create.isPending ? 'Creating…' : 'Create Project'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/')}
            style={{
              padding: '10px 16px',
              background: 'none',
              border: '1px solid var(--border)',
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

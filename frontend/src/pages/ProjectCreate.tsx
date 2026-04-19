import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import DimensionEditor from '../components/DimensionEditor'
import type { RatingDimension } from '../api/types'

const DEFAULT_DIMS: RatingDimension[] = [
  { name: 'Prose Quality', description: 'Clarity, style and craft of the writing', weight: 1.0 },
  { name: 'Pacing', description: 'Narrative flow and engagement', weight: 1.0 },
  { name: 'Atmosphere', description: 'World-building, setting and mood', weight: 1.0 },
  { name: 'Character', description: 'Depth and authenticity of characterisation', weight: 1.0 },
  { name: 'Originality', description: 'Freshness of ideas and subversion of expectations', weight: 1.0 },
]

export default function ProjectCreate() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [threshold, setThreshold] = useState(50)
  const [dims, setDims] = useState<RatingDimension[]>(DEFAULT_DIMS)

  const create = useMutation({
    mutationFn: () => api.projects.create({
      name,
      description: description || undefined,
      domain: 'text',
      rating_dimensions: dims,
      crystallisation_threshold: threshold,
    }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${p.id}`)
    },
  })

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: 24 }}>
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
            style={{ width: 100 }}
          />
        </div>
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

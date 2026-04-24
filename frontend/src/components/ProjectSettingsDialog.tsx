import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import DimensionEditor from './DimensionEditor'
import type { Project, Rating, RatingDimension } from '../api/types'

interface Props {
  project: Project
  ratings: Rating[]
  onClose: () => void
}

export default function ProjectSettingsDialog({ project, ratings, onClose }: Props) {
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [threshold, setThreshold] = useState(project.crystallisation_threshold)
  const [chunkMin, setChunkMin] = useState(project.chunk_min_size)
  const [chunkMax, setChunkMax] = useState(project.chunk_max_size)
  const [dims, setDims] = useState<RatingDimension[]>(project.rating_dimensions)

  const originalNames = project.rating_dimensions.map(d => d.name)
  const originalDescriptions = project.rating_dimensions.map(d => d.description)
  const ratedNames = new Set(ratings.flatMap(r => Object.keys(r.dimension_scores)))

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
        chunk_min_size: chunkMin,
        chunk_max_size: chunkMax,
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
              <div>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Chunk size (min / max words)</label>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input
                    type="number" min={100} value={chunkMin}
                    onChange={e => setChunkMin(Number(e.target.value))}
                    style={{ ...inputStyle, width: 80 }}
                  />
                  <span style={{ color: 'var(--text-muted)' }}>–</span>
                  <input
                    type="number" min={100} value={chunkMax}
                    onChange={e => setChunkMax(Number(e.target.value))}
                    style={{ ...inputStyle, width: 80 }}
                  />
                </div>
              </div>
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

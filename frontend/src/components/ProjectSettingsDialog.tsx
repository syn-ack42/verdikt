import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
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

  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [threshold, setThreshold] = useState(project.crystallisation_threshold)
  const [chunkMin, setChunkMin] = useState(project.chunk_min_size)
  const [chunkMax, setChunkMax] = useState(project.chunk_max_size)
  const [dims, setDims] = useState<RatingDimension[]>(project.rating_dimensions)

  const originalNames = project.rating_dimensions.map(d => d.name)
  const originalDescriptions = project.rating_dimensions.map(d => d.description)
  const ratedNames = new Set(ratings.flatMap(r => Object.keys(r.dimension_scores)))

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

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#fff', color: '#1a1a1a', borderRadius: 10, width: 680, maxHeight: '85vh',
        display: 'flex', flexDirection: 'column', boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Project Settings</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#888' }}>×</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          <form id="settings-form" onSubmit={e => { e.preventDefault(); save.mutate() }}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Name</label>
              <input
                required
                value={name}
                onChange={e => setName(e.target.value)}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Description</label>
              <input
                value={description}
                onChange={e => setDescription(e.target.value)}
                style={{ width: '100%' }}
              />
            </div>

            <div style={{ marginBottom: 16, display: 'flex', gap: 24 }}>
              <div>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Crystallisation threshold</label>
                <input
                  type="number"
                  min={1}
                  value={threshold}
                  onChange={e => setThreshold(Number(e.target.value))}
                  style={{ width: 100 }}
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: 4, fontSize: 13, fontWeight: 600 }}>Chunk size (min / max words)</label>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input
                    type="number"
                    min={100}
                    value={chunkMin}
                    onChange={e => setChunkMin(Number(e.target.value))}
                    style={{ width: 80 }}
                  />
                  <span style={{ color: '#888' }}>–</span>
                  <input
                    type="number"
                    min={100}
                    value={chunkMax}
                    onChange={e => setChunkMax(Number(e.target.value))}
                    style={{ width: 80 }}
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
        </div>

        <div style={{ padding: '12px 20px', borderTop: '1px solid #e0e0e0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {save.error && (
            <span style={{ fontSize: 13, color: '#c00' }}>{String(save.error)}</span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={onClose}
              style={{ padding: '6px 14px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              form="settings-form"
              disabled={save.isPending}
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

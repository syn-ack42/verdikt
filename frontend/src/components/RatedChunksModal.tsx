import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import RatingSlider from './RatingSlider'
import type { RatedChunkEntry } from '../api/types'

interface Props {
  projectId: string
  filterWorkSeq?: number
  filterWorkTitle?: string
  dimensions: { name: string; description: string; weight: number }[]
  onClose: () => void
}

function scoreColor(avg: number | null): string {
  if (avg == null) return 'var(--text-muted)'
  if (avg >= 4) return '#2e7d32'
  if (avg >= 3) return '#6b7de0'
  if (avg >= 2) return '#b45309'
  return '#c00'
}

export default function RatedChunksModal({ projectId, filterWorkSeq, filterWorkTitle, dimensions, onClose }: Props) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<RatedChunkEntry | null>(null)
  const [scores, setScores] = useState<Record<string, number>>({})
  const [activeIdx, setActiveIdx] = useState(0)

  const { data: entries, isLoading } = useQuery({
    queryKey: ['rated-chunks', projectId, filterWorkSeq],
    queryFn: () => api.ratings.ratedChunks(projectId, filterWorkSeq),
  })

  const updateRating = useMutation({
    mutationFn: ({ ratingId, scores }: { ratingId: string; scores: Record<string, number> }) =>
      api.ratings.updateRating(projectId, ratingId, scores),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rated-chunks', projectId] })
      qc.invalidateQueries({ queryKey: ['ratings', projectId] })
      setEditing(null)
    },
  })

  const openEdit = (entry: RatedChunkEntry) => {
    setEditing(entry)
    setScores({ ...entry.dimension_scores })
    setActiveIdx(0)
  }

  const allScored = dimensions.length > 0 && dimensions.every(d => scores[d.name] !== undefined)

  const title = filterWorkTitle
    ? `Ratings — ${filterWorkTitle}`
    : 'Ratings'

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)', color: 'var(--text)',
        borderRadius: 10, width: 820, maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {editing && (
              <button onClick={() => setEditing(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 14, padding: 0 }}>
                ← Back
              </button>
            )}
            <h3 style={{ margin: 0, fontSize: 16 }}>{editing ? 'Edit Rating' : title}</h3>
            {!editing && entries && (
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{entries.length} rated</span>
            )}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {isLoading && <p style={{ padding: 20, color: 'var(--text-muted)' }}>Loading…</p>}

          {/* Edit view */}
          {editing && (
            <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {editing.work_title ?? 'Unknown work'}
                {editing.author && ` — ${editing.author}`}
                {' · '}chunk {editing.chunk_position + 1} of {editing.chunk_count}
              </div>
              <div style={{
                background: 'var(--surface, rgba(128,128,128,0.08))',
                border: '1px solid var(--border)',
                borderRadius: 8, padding: '12px 16px',
                lineHeight: 1.7, fontSize: 14, whiteSpace: 'pre-wrap',
                maxHeight: 320, overflowY: 'auto',
                fontFamily: 'Georgia, serif',
              }}>
                {editing.chunk_content ?? '(binary content)'}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {dimensions.map((dim, i) => (
                  <RatingSlider
                    key={dim.name}
                    name={dim.name}
                    score={scores[dim.name]}
                    active={activeIdx === i}
                    onScore={v => setScores(s => ({ ...s, [dim.name]: v }))}
                    onFocus={() => setActiveIdx(i)}
                  />
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => updateRating.mutate({ ratingId: editing.rating_id, scores })}
                  disabled={!allScored || updateRating.isPending}
                  style={{
                    padding: '7px 20px', borderRadius: 4, border: 'none', cursor: allScored ? 'pointer' : 'default',
                    background: allScored ? '#6b7de0' : 'var(--border)', color: allScored ? '#fff' : 'var(--text-muted)',
                  }}
                >
                  {updateRating.isPending ? 'Saving…' : 'Save'}
                </button>
                <button onClick={() => setEditing(null)} style={{ padding: '7px 14px', borderRadius: 4 }}>
                  Cancel
                </button>
                {updateRating.error && (
                  <span style={{ fontSize: 13, color: '#c00', alignSelf: 'center' }}>
                    {String(updateRating.error)}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* List view */}
          {!editing && entries && entries.length === 0 && (
            <p style={{ padding: 20, color: 'var(--text-muted)' }}>No ratings yet.</p>
          )}
          {!editing && entries && entries.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)', textAlign: 'left' }}>
                  <th style={{ padding: '8px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>Work</th>
                  <th style={{ padding: '8px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>Chunk</th>
                  <th style={{ padding: '8px 8px', color: 'var(--text-muted)', fontWeight: 500, textAlign: 'right' }}>Avg</th>
                  {dimensions.map(d => (
                    <th key={d.name} style={{ padding: '8px 8px', color: 'var(--text-muted)', fontWeight: 500, textAlign: 'right' }}>
                      {d.name}
                    </th>
                  ))}
                  <th style={{ padding: '8px 8px' }}></th>
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => (
                  <tr
                    key={entry.rating_id}
                    style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                    onClick={() => openEdit(entry)}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover, rgba(128,128,128,0.06))')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >
                    <td style={{ padding: '7px 12px' }}>
                      {entry.work_seq != null ? <span style={{ color: 'var(--text-muted)', marginRight: 6 }}>#{entry.work_seq}</span> : null}
                      <span>{entry.work_title ?? entry.material_item_id.slice(0, 8)}</span>
                    </td>
                    <td style={{ padding: '7px 12px', color: 'var(--text-muted)' }}>
                      {entry.chunk_position + 1} of {entry.chunk_count}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right', fontWeight: 600, color: scoreColor(entry.avg_score) }}>
                      {entry.avg_score?.toFixed(1) ?? '—'}
                    </td>
                    {dimensions.map(d => (
                      <td key={d.name} style={{ padding: '7px 8px', textAlign: 'right', color: 'var(--text-muted)' }}>
                        {entry.dimension_scores[d.name] ?? '—'}
                      </td>
                    ))}
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      <span style={{ color: '#6b7de0', fontSize: 11 }}>Edit</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

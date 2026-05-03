import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import RatingSlider from './RatingSlider'
import { useIsMobile } from '../hooks/useIsMobile'
import type { RatedChunkEntry } from '../api/types'

interface Props {
  projectId: string
  filterWorkSeq?: number
  filterWorkTitle?: string
  dimensions: { name: string; description: string; weight: number }[]
  onClose: () => void
  /** When set, open directly in edit/create mode for this entry (skips the list). */
  initialEditing?: RatedChunkEntry
}

function scoreColor(avg: number | null): string {
  if (avg == null) return 'var(--text-muted)'
  if (avg >= 4) return '#2e7d32'
  if (avg >= 3) return '#6b7de0'
  if (avg >= 2) return '#b45309'
  return '#c00'
}

export default function RatedChunksModal({ projectId, filterWorkSeq, filterWorkTitle, dimensions, onClose, initialEditing }: Props) {
  const isMobile = useIsMobile()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<RatedChunkEntry | null>(initialEditing ?? null)
  const [expandedExpl, setExpandedExpl] = useState<string | null>(null)
  const [scores, setScores] = useState<Record<string, number>>(initialEditing?.dimension_scores ?? {})
  const [activeIdx, setActiveIdx] = useState(0)
  const [sortBy, setSortBy] = useState<string>('chunk_position')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 50

  const { data: entries, isLoading } = useQuery({
    queryKey: ['rated-chunks', projectId, filterWorkSeq],
    queryFn: () => api.ratings.ratedChunks(projectId, filterWorkSeq),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['rated-chunks', projectId] })
    qc.invalidateQueries({ queryKey: ['ratings', projectId] })
    qc.invalidateQueries({ queryKey: ['work-chunks', projectId] })
    qc.invalidateQueries({ queryKey: ['works', projectId] })
  }

  const updateRating = useMutation({
    mutationFn: ({ ratingId, scores }: { ratingId: string; scores: Record<string, number> }) =>
      api.ratings.updateRating(projectId, ratingId, scores),
    onSuccess: () => { invalidate(); initialEditing ? onClose() : setEditing(null) },
  })

  const createRating = useMutation({
    mutationFn: ({ chunkId, materialItemId, scores }: { chunkId: string; materialItemId: string; scores: Record<string, number> }) =>
      api.ratings.submit(projectId, { chunk_id: chunkId, material_item_id: materialItemId, dimension_scores: scores }),
    onSuccess: () => { invalidate(); initialEditing ? onClose() : setEditing(null) },
  })

  const openEdit = (entry: RatedChunkEntry) => {
    setEditing(entry)
    setScores({ ...entry.dimension_scores })
    setActiveIdx(0)
  }

  const isNewRating = editing?.rating_id === ''
  const isPending = updateRating.isPending || createRating.isPending
  const saveError = updateRating.error || createRating.error

  const allScored = dimensions.length > 0 && dimensions.every(d => scores[d.name] !== undefined)

  const getVal = (entry: RatedChunkEntry, col: string): any => {
    if (col.startsWith('dim:')) return entry.dimension_scores[col.slice(4)] ?? null
    return (entry as any)[col]
  }

  const sortedEntries = entries ? [...entries].sort((a, b) => {
    const av = getVal(a, sortBy)
    const bv = getVal(b, sortBy)
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (av < bv) return sortDir === 'asc' ? -1 : 1
    if (av > bv) return sortDir === 'asc' ? 1 : -1
    return 0
  }) : []

  const pagedEntries = sortedEntries.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

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
        borderRadius: 10, width: 'min(820px, 94vw)', maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {editing && !initialEditing && (
              <button onClick={() => setEditing(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 14, padding: 0 }}>
                ← Back
              </button>
            )}
            <h3 style={{ margin: 0, fontSize: 16 }}>{editing ? (isNewRating ? 'Rate Chunk' : 'Edit Rating') : title}</h3>
            {!editing && entries && (
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                {entries.length} rated{sortedEntries.length > PAGE_SIZE && ` · page ${page + 1} of ${Math.ceil(sortedEntries.length / PAGE_SIZE)}`}
              </span>
            )}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
          {isLoading && <p style={{ padding: 20, color: 'var(--text-muted)' }}>Loading…</p>}

          {/* Edit view */}
          {editing && (
            <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {editing.work_title ?? 'Unknown work'}
                {editing.author && ` — ${editing.author}`}
                {editing.chunk_count > 1 && ` · chunk ${editing.chunk_position + 1} of ${editing.chunk_count}`}
              </div>
              {editing.chunk_domain === 'image' && editing.chunk_content ? (
                <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 8 }}>
                  <img src={`data:image/jpeg;base64,${editing.chunk_content}`} alt="rated image" style={{ maxWidth: '100%', maxHeight: 'clamp(150px, 30vh, 320px)', objectFit: 'contain', borderRadius: 4 }} />
                </div>
              ) : (
                <div style={{
                  background: 'var(--surface, rgba(128,128,128,0.08))',
                  border: '1px solid var(--border)',
                  borderRadius: 8, padding: '12px 16px',
                  lineHeight: 1.7, fontSize: 14, whiteSpace: 'pre-wrap',
                  maxHeight: 'clamp(150px, 30vh, 320px)', overflowY: 'auto',
                  fontFamily: 'Georgia, serif',
                }}>
                  {editing.chunk_content ?? '(no content)'}
                </div>
              )}
              {editing.chunk_description && (
                <div style={{ fontSize: 12, borderRadius: 6, background: 'rgba(107,125,224,0.06)', border: '1px solid rgba(107,125,224,0.13)', padding: '6px 10px', lineHeight: 1.5, color: 'var(--text)' }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: '#6b7de0', marginRight: 6, letterSpacing: '0.05em' }}>AI</span>
                  {editing.chunk_description}
                </div>
              )}
              {editing.explanations && Object.keys(editing.explanations).length > 0 && (
                <div
                  onClick={() => setExpandedExpl(expandedExpl === editing.rating_id ? null : editing.rating_id)}
                  style={{ borderRadius: 6, background: 'var(--surface, rgba(128,128,128,0.06))', padding: '6px 12px', cursor: 'pointer', fontSize: 12, color: 'var(--text-muted)' }}
                >
                  {expandedExpl === editing.rating_id ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {Object.entries(editing.explanations).map(([k, v]) => (
                        <div key={k}><span style={{ fontWeight: 600, color: 'var(--text)' }}>{k}:</span> {v}</div>
                      ))}
                      <span style={{ fontSize: 11, marginTop: 2 }}>▴ collapse</span>
                    </div>
                  ) : (
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <span style={{ marginRight: 6, fontSize: 11 }}>▾</span>
                      {Object.entries(editing.explanations).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                    </div>
                  )}
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 4 }}>
                {dimensions.map((dim, i) => (
                  <RatingSlider
                    key={dim.name}
                    name={dim.name}
                    description={dim.description}
                    score={scores[dim.name]}
                    active={activeIdx === i}
                    onScore={v => setScores(s => ({ ...s, [dim.name]: v }))}
                    onFocus={() => setActiveIdx(i)}
                  />
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => {
                    if (isNewRating) {
                      createRating.mutate({ chunkId: editing.chunk_id, materialItemId: editing.material_item_id, scores })
                    } else {
                      updateRating.mutate({ ratingId: editing.rating_id, scores })
                    }
                  }}
                  disabled={!allScored || isPending}
                  style={{
                    padding: '7px 20px', borderRadius: 4, border: 'none', cursor: allScored ? 'pointer' : 'default',
                    background: allScored ? '#6b7de0' : 'var(--border)', color: allScored ? '#fff' : 'var(--text-muted)',
                  }}
                >
                  {isPending ? 'Saving…' : isNewRating ? 'Add rating' : 'Save'}
                </button>
                <button onClick={() => initialEditing ? onClose() : setEditing(null)} style={{ padding: '7px 14px', borderRadius: 4 }}>
                  Cancel
                </button>
                {saveError && (
                  <span style={{ fontSize: 13, color: '#c00', alignSelf: 'center' }}>
                    {String(saveError)}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Sort bar */}
          {!editing && entries && entries.length > 0 && (
            <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>Sort</span>
              <select
                value={sortBy}
                onChange={e => { setSortBy(e.target.value); setSortDir('asc'); setPage(0) }}
                style={{ fontSize: 12, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', cursor: 'pointer' }}
              >
                <option value="chunk_position">Chunk</option>
                <option value="work_seq">Work</option>
                <option value="avg_score">Avg score</option>
                <option value="is_ai">Source</option>
                {dimensions.map(d => <option key={d.name} value={`dim:${d.name}`}>{d.name}</option>)}
              </select>
              <button
                onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
                style={{ fontSize: 11, padding: '2px 7px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: 'var(--text)', cursor: 'pointer' }}
              >
                {sortDir === 'asc' ? '▴' : '▾'}
              </button>
            </div>
          )}

          {/* List view — cards */}
          {!editing && entries && entries.length === 0 && (
            <p style={{ padding: 20, color: 'var(--text-muted)' }}>No ratings yet.</p>
          )}
          {!editing && entries && entries.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {pagedEntries.map(entry => {
                const hasExpl = entry.explanations && Object.keys(entry.explanations).length > 0
                const explExpanded = expandedExpl === entry.rating_id
                // Combine all explanations into one summary line
                const explPreview = hasExpl
                  ? Object.entries(entry.explanations).map(([k, v]) => `${k}: ${v}`).join(' · ')
                  : null
                return (
                  <div key={entry.rating_id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <div
                      onClick={() => openEdit(entry)}
                      style={{ padding: '12px 16px', cursor: 'pointer' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover, rgba(128,128,128,0.06))')}
                      onMouseLeave={e => (e.currentTarget.style.background = '')}
                    >
                      {/* Title + avg row */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4, gap: 8 }}>
                        <div style={{ fontWeight: 500, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
                          {entry.work_seq != null && <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginRight: 6, fontSize: 12 }}>#{entry.work_seq}</span>}
                          {entry.work_title ?? entry.material_item_id.slice(0, 8)}
                        </div>
                        {entry.avg_score != null && (
                          <span style={{ fontSize: 18, fontWeight: 700, color: scoreColor(entry.avg_score), flexShrink: 0 }}>
                            {entry.avg_score.toFixed(1)}
                          </span>
                        )}
                      </div>

                      {/* Meta row */}
                      <div style={{ display: 'flex', gap: 8, fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                        {entry.chunk_count > 1 && (
                          <span>Chunk {entry.chunk_position + 1} of {entry.chunk_count}</span>
                        )}
                        {entry.is_ai ? (
                          <span style={{ background: 'rgba(180,83,9,0.12)', color: '#b45309', fontSize: 10, padding: '2px 5px', borderRadius: 3, fontWeight: 600 }}>AI</span>
                        ) : (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            Human
                            {entry.also_ai_rated && (
                              <span style={{ border: '1px dashed #b45309', color: '#b45309', fontSize: 10, padding: '0px 4px', borderRadius: 3, fontWeight: 600, opacity: 0.7 }} title="This chunk was also rated by AI">AI</span>
                            )}
                          </span>
                        )}
                      </div>

                      {/* Dimension grid */}
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 8px' }}>
                        {dimensions.map(d => {
                          const score = entry.dimension_scores[d.name]
                          return (
                            <div key={d.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--surface, rgba(128,128,128,0.06))', borderRadius: 4, padding: '4px 8px' }}>
                              <span style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 4 }}>{d.name}</span>
                              <span style={{ fontSize: 13, fontWeight: 600, flexShrink: 0, color: score != null ? scoreColor(score) : 'var(--text-muted)' }}>
                                {score != null ? score.toFixed(1) : '—'}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    {/* Explanation row */}
                    {hasExpl && (
                      <div
                        onClick={e => { e.stopPropagation(); setExpandedExpl(explExpanded ? null : entry.rating_id) }}
                        style={{ padding: '4px 16px 10px', cursor: 'pointer', background: 'var(--surface, rgba(128,128,128,0.05))' }}
                      >
                        {explExpanded ? (
                          <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {Object.entries(entry.explanations).map(([k, v]) => (
                              <div key={k}><span style={{ fontWeight: 600, color: 'var(--text)' }}>{k}:</span> {v}</div>
                            ))}
                            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>▴ collapse</span>
                          </div>
                        ) : (
                          <div style={{ fontSize: 12, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <span style={{ marginRight: 6, fontSize: 11 }}>▾</span>{explPreview}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {!editing && sortedEntries.length > PAGE_SIZE && (
            <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13, color: 'var(--text-muted)', flexShrink: 0 }}>
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: page === 0 ? 'var(--text-muted)' : 'var(--text)', cursor: page === 0 ? 'default' : 'pointer' }}
              >← Prev</button>
              <span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sortedEntries.length)} of {sortedEntries.length}</span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={(page + 1) * PAGE_SIZE >= sortedEntries.length}
                style={{ padding: '4px 12px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: (page + 1) * PAGE_SIZE >= sortedEntries.length ? 'var(--text-muted)' : 'var(--text)', cursor: (page + 1) * PAGE_SIZE >= sortedEntries.length ? 'default' : 'pointer' }}
              >Next →</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

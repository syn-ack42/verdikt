import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import RatingSlider from './RatingSlider'
import { useIsMobile } from '../hooks/useIsMobile'
import type { RatingDimension, WorkChunk } from '../api/types'

interface Props {
  projectId: string
  chunk: WorkChunk
  chunkLabel: string   // e.g. "Chunk 3 of 7"
  dimensions: RatingDimension[]
  onClose: () => void
}

export default function RatingEditModal({ projectId, chunk, chunkLabel, dimensions, onClose }: Props) {
  const isMobile = useIsMobile()
  const qc = useQueryClient()
  const r = chunk.rating
  const isEdit = r !== null

  const [scores, setScores] = useState<Record<string, number>>(
    r ? { ...r.dimension_scores } : {}
  )
  const [activeIdx, setActiveIdx] = useState(0)
  const [expandedExpl, setExpandedExpl] = useState(false)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['work-chunks', projectId] })
    qc.invalidateQueries({ queryKey: ['rated-chunks', projectId] })
    qc.invalidateQueries({ queryKey: ['works', projectId] })
  }

  const updateRating = useMutation({
    mutationFn: () => api.ratings.updateRating(projectId, r!.rating_id, scores),
    onSuccess: () => { invalidate(); onClose() },
  })

  const createRating = useMutation({
    mutationFn: () => api.ratings.submit(projectId, {
      chunk_id: chunk.chunk_id,
      material_item_id: chunk.material_item_id,
      dimension_scores: scores,
    }),
    onSuccess: () => { invalidate(); onClose() },
  })

  const isPending = updateRating.isPending || createRating.isPending
  const err = updateRating.error || createRating.error
  const allScored = dimensions.length > 0 && dimensions.every(d => scores[d.name] !== undefined)
  const hasExpl = r && Object.keys(r.explanations).length > 0

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)', color: 'var(--text)',
        borderRadius: 10, width: 'min(600px, 94vw)', maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 15 }}>{isEdit ? 'Edit Rating' : 'Rate Chunk'}</h3>
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
              {chunkLabel}
              {r && (
                <span style={{ marginLeft: 8 }}>
                  {r.is_ai ? (
                    <span style={{ background: 'rgba(180,83,9,0.15)', color: '#b45309', fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 700 }}>AI</span>
                  ) : (
                    <span style={{ background: 'rgba(46,125,50,0.12)', color: '#2e7d32', fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 700 }}>Human</span>
                  )}
                </span>
              )}
            </p>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)', flexShrink: 0 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Chunk content preview */}
          {chunk.domain === 'image' && chunk.content ? (
            <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 8 }}>
              <img
                src={`data:image/jpeg;base64,${chunk.content}`}
                alt="chunk"
                style={{ maxWidth: '100%', maxHeight: 'clamp(150px, 28vh, 300px)', objectFit: 'contain', borderRadius: 4 }}
              />
            </div>
          ) : chunk.content ? (
            <div style={{
              background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6,
              padding: '10px 14px', maxHeight: 'clamp(120px, 26vh, 280px)', overflowY: 'auto',
              fontSize: 14, lineHeight: 1.75, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              fontFamily: 'Georgia, serif',
            }}>
              {chunk.content}
            </div>
          ) : null}

          {/* AI explanations */}
          {hasExpl && (
            <div
              onClick={() => setExpandedExpl(v => !v)}
              style={{ borderRadius: 6, background: 'var(--surface, rgba(128,128,128,0.06))', padding: '6px 12px', cursor: 'pointer', fontSize: 12, color: 'var(--text-muted)' }}
            >
              {expandedExpl ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {Object.entries(r!.explanations).map(([k, v]) => (
                    <div key={k}><span style={{ fontWeight: 600, color: 'var(--text)' }}>{k}:</span> {v}</div>
                  ))}
                  <span style={{ fontSize: 11, marginTop: 2 }}>▴ collapse</span>
                </div>
              ) : (
                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <span style={{ marginRight: 6, fontSize: 11 }}>▾</span>
                  {Object.entries(r!.explanations).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </div>
              )}
            </div>
          )}

          {/* Sliders */}
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 4 }}>
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
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 18px', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={() => isEdit ? updateRating.mutate() : createRating.mutate()}
            disabled={!allScored || isPending}
            style={{
              padding: '7px 20px', borderRadius: 4, border: 'none', fontSize: 14,
              cursor: allScored && !isPending ? 'pointer' : 'default',
              background: allScored ? '#6b7de0' : 'var(--border)',
              color: allScored ? '#fff' : 'var(--text-muted)',
            }}
          >
            {isPending ? 'Saving…' : isEdit ? 'Save' : 'Add rating'}
          </button>
          <button
            onClick={onClose}
            style={{ padding: '7px 14px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', fontSize: 14 }}
          >
            Cancel
          </button>
          {err && <span style={{ fontSize: 12, color: '#c00' }}>{String(err)}</span>}
        </div>
      </div>
    </div>
  )
}

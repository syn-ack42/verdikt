import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import RatedChunksModal from './RatedChunksModal'
import type { RatedChunkEntry, RatingDimension, WorkChunk, WorkDetail } from '../api/types'

interface Props {
  projectId: string
  workRef: string | number
  dimensions: RatingDimension[]
  onClose: () => void
  onRemove?: (workRef: string | number) => void
}

function scoreColor(avg: number | null): string {
  if (avg == null) return 'var(--text-muted)'
  if (avg >= 4) return '#2e7d32'
  if (avg >= 3) return '#6b7de0'
  if (avg >= 2) return '#b45309'
  return '#c00'
}

function toRatedChunkEntry(chunk: WorkChunk, work: WorkDetail): RatedChunkEntry {
  return {
    rating_id: chunk.rating?.rating_id ?? '',
    chunk_id: chunk.chunk_id,
    chunk_position: chunk.position,
    chunk_count: chunk.chunk_count,
    chunk_content: chunk.content,
    chunk_domain: chunk.domain,
    chunk_description: chunk.description,
    material_item_id: chunk.material_item_id,
    work_seq: work.project_seq,
    work_title: work.work_title,
    author: work.author,
    dimension_scores: chunk.rating?.dimension_scores ?? {},
    avg_score: chunk.rating?.avg_score ?? null,
    is_ai: chunk.rating?.is_ai ?? false,
    explanations: chunk.rating?.explanations ?? {},
    rated_at: chunk.rating?.rated_at ?? '',
  }
}

function ChunkBlock({
  chunk,
  work,
  dimensions,
  projectId,
  collapsed,
  onToggleCollapse,
}: {
  chunk: WorkChunk
  work: WorkDetail
  dimensions: RatingDimension[]
  projectId: string
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  const [editOpen, setEditOpen] = useState(false)
  const [aiRating, setAiRating] = useState(false)
  const [aiError, setAiError] = useState<string | null>(null)
  const qc = useQueryClient()
  const r = chunk.rating
  const pos = chunk.position + 1
  const total = chunk.chunk_count

  async function triggerAiRating() {
    setAiRating(true)
    setAiError(null)
    try {
      await api.ratings.rateChunkAI(projectId, chunk.chunk_id, chunk.material_item_id)
      qc.invalidateQueries({ queryKey: ['work-chunks', projectId] })
    } catch (e: unknown) {
      setAiError(e instanceof Error ? e.message : 'AI rating failed')
    } finally {
      setAiRating(false)
    }
  }

  return (
    <>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        {/* Header */}
        <div
          onClick={e => { if ((e.target as HTMLElement).closest('button') === null) onToggleCollapse() }}
          style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '6px 12px',
            background: 'var(--surface, rgba(128,128,128,0.06))',
            borderBottom: collapsed ? 'none' : '1px solid var(--border)',
            gap: 8,
            flexWrap: 'wrap',
            cursor: 'pointer',
            userSelect: 'none',
          }}
        >
          <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ fontSize: 10, opacity: 0.6 }}>{collapsed ? '▸' : '▾'}</span>
            Chunk {pos} of {total}
          </span>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            {r ? (
              <button
                onClick={() => setEditOpen(true)}
                title="Edit rating"
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  background: 'none', border: '1px solid var(--border)',
                  borderRadius: 20, padding: '2px 10px', cursor: 'pointer', fontSize: 12,
                }}
              >
                {r.is_ai ? (
                  <span style={{ background: 'rgba(180,83,9,0.15)', color: '#b45309', fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 700 }}>AI</span>
                ) : (
                  <>
                    <span style={{ background: 'rgba(46,125,50,0.12)', color: '#2e7d32', fontSize: 10, padding: '1px 5px', borderRadius: 3, fontWeight: 700 }}>Human</span>
                    {r.also_ai_rated && (
                      <span style={{ border: '1px dashed #b45309', color: '#b45309', fontSize: 10, padding: '0px 4px', borderRadius: 3, fontWeight: 600, opacity: 0.7 }} title="This chunk was also rated by AI">AI</span>
                    )}
                  </>
                )}
                {r.avg_score != null && (
                  <span style={{ fontWeight: 700, color: scoreColor(r.avg_score) }}>{r.avg_score.toFixed(1)}</span>
                )}
                {dimensions.map(d => (
                  <span key={d.name} style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {d.name[0].toUpperCase()}{d.name[1] ?? ''}:&thinsp;
                    <span style={{ color: scoreColor(r.dimension_scores[d.name] ?? null), fontWeight: 600 }}>
                      {r.dimension_scores[d.name] != null ? r.dimension_scores[d.name].toFixed(1) : '—'}
                    </span>
                  </span>
                ))}
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>✎</span>
              </button>
            ) : (
              <button
                onClick={() => setEditOpen(true)}
                style={{
                  background: 'none', border: '1px dashed var(--border)',
                  borderRadius: 20, padding: '2px 10px', cursor: 'pointer',
                  fontSize: 12, color: 'var(--text-muted)',
                }}
              >
                + rate
              </button>
            )}

            <button
              onClick={triggerAiRating}
              disabled={aiRating}
              title={r?.is_ai ? 'Re-rate with AI' : r ? 'Rate with AI (replaces existing AI rating if any)' : 'Rate with AI'}
              style={{
                background: 'none', border: '1px solid var(--border)',
                borderRadius: 20, padding: '2px 8px', cursor: aiRating ? 'default' : 'pointer',
                fontSize: 11, color: aiRating ? 'var(--text-muted)' : '#b45309',
                display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              <span style={aiRating ? { display: 'inline-block', animation: 'spin 1s linear infinite' } : {}}>↺</span>
              {aiRating ? 'AI…' : 'AI'}
            </button>
          </div>

          {aiError && (
            <span style={{ fontSize: 11, color: '#c00', width: '100%' }}>{aiError}</span>
          )}
        </div>

        {/* Content — hidden when collapsed */}
        {!collapsed && (
          <div style={{ padding: '10px 14px 6px' }}>
            {chunk.domain === 'image' && chunk.content ? (
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <img
                  src={`data:image/jpeg;base64,${chunk.content}`}
                  alt={`Chunk ${pos}`}
                  style={{ maxWidth: '100%', maxHeight: 280, objectFit: 'contain', borderRadius: 4 }}
                />
              </div>
            ) : (
              <div style={{ fontSize: 14, lineHeight: 1.75, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'Georgia, serif' }}>
                {chunk.content ?? <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>(no content)</span>}
              </div>
            )}
          </div>
        )}

        {/* Description — always visible */}
        {chunk.description && (
          <div style={{ padding: collapsed ? '5px 14px 7px' : '0 14px 8px', fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', lineHeight: 1.5 }}>
            {chunk.description}
          </div>
        )}
      </div>

      {editOpen && (
        <RatedChunksModal
          projectId={projectId}
          dimensions={dimensions}
          initialEditing={toRatedChunkEntry(chunk, work)}
          onClose={() => setEditOpen(false)}
        />
      )}
    </>
  )
}

export default function WorkDetailModal({ projectId, workRef, dimensions, onClose, onRemove }: Props) {
  const { data: work, isLoading, error } = useQuery({
    queryKey: ['work-detail', projectId, workRef],
    queryFn: () => api.works.detail(projectId, String(workRef)),
  })

  const { data: chunks, isLoading: chunksLoading } = useQuery({
    queryKey: ['work-chunks', projectId, workRef],
    queryFn: () => api.works.chunks(projectId, String(workRef)),
    enabled: !!work,
  })

  const [collapsedChunks, setCollapsedChunks] = useState<Set<string>>(new Set())

  const hasChunks = chunks && chunks.length > 0
  const allCollapsed = hasChunks && collapsedChunks.size === chunks.length

  function toggleChunk(id: string) {
    setCollapsedChunks(s => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)', color: 'var(--text)',
        borderRadius: 10, width: 'min(820px, 94vw)', maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)', overflow: 'hidden',
        border: '1px solid var(--border)',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 16, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {work?.work_title ?? (isLoading ? 'Loading…' : 'Work Detail')}
            </h3>
            {work?.author && <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{work.author}</p>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)', flexShrink: 0 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', minWidth: 0, padding: 'clamp(12px, 4vw, 20px)', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}
          {error && <p style={{ color: '#c00' }}>Failed to load work details.</p>}

          {work && (
            <>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
                  <tbody>
                    <MetaRow label="Source">{work.source_plugin}</MetaRow>
                    <MetaRow label="Status">
                      <span style={{
                        background: work.pipeline_phase === 'clustered' ? 'var(--badge-green-bg)' : 'var(--badge-yellow-bg)',
                        color: work.pipeline_phase === 'clustered' ? 'var(--badge-green-text)' : 'var(--badge-yellow-text)',
                        padding: '1px 6px', borderRadius: 3, fontSize: 11,
                      }}>
                        {work.pipeline_phase === 'clustered' ? 'processed' : work.pipeline_phase}
                      </span>
                    </MetaRow>
                    <MetaRow label="Ingested">{work.ingested_at.slice(0, 10)}</MetaRow>
                    {work.content_hash && (
                      <MetaRow label="Hash">
                        <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{work.content_hash.slice(0, 16)}…</span>
                      </MetaRow>
                    )}

                    {/* AO3 */}
                    {work.source_plugin === 'ao3' && work.plugin_metadata.work_id != null && (
                      <MetaRow label="Work ID">{String(work.plugin_metadata.work_id)}</MetaRow>
                    )}
                    {work.source_plugin === 'ao3' && work.plugin_metadata.source_updated_at != null && (
                      <MetaRow label="Last updated">{String(work.plugin_metadata.source_updated_at).slice(0, 10)}</MetaRow>
                    )}
                    {work.source_plugin === 'ao3' && work.url && (
                      <MetaRow label="URL">
                        <a href={work.url} target="_blank" rel="noopener noreferrer"
                          style={{ color: '#6b7de0', wordBreak: 'break-all' }}>
                          {work.url}
                        </a>
                      </MetaRow>
                    )}

                    {/* Storage / Filedrop */}
                    {(work.source_plugin === 'filedrop' || work.source_plugin === 'storage') && (
                      <MetaRow label="File">
                        <span style={{ fontFamily: 'monospace', wordBreak: 'break-all', fontSize: 12 }}>
                          {work.storage_path ?? work.source_path}
                        </span>
                        {work.storage_path && (
                          <a href={api.storage.downloadUrl(work.storage_path)} download
                            style={{ marginLeft: 10, fontSize: 12, padding: '2px 8px', background: '#6b7de0', color: '#fff', borderRadius: 4, textDecoration: 'none' }}>
                            Download
                          </a>
                        )}
                      </MetaRow>
                    )}

                    {/* Immich */}
                    {work.source_plugin === 'immich' && work.url && (
                      <MetaRow label="URL">
                        <a href={work.url} target="_blank" rel="noopener noreferrer"
                          style={{ color: '#6b7de0', wordBreak: 'break-all' }}>
                          {work.url}
                        </a>
                      </MetaRow>
                    )}
                    {work.source_plugin === 'immich' && work.plugin_metadata.original_filename != null && (
                      <MetaRow label="Filename">{String(work.plugin_metadata.original_filename)}</MetaRow>
                    )}
                    {work.source_plugin === 'immich' && work.plugin_metadata.file_created_at != null && (
                      <MetaRow label="Captured">{String(work.plugin_metadata.file_created_at).slice(0, 10)}</MetaRow>
                    )}

                    {/* Generic fallback for any other plugin */}
                    {!['ao3', 'filedrop', 'storage', 'immich'].includes(work.source_plugin) &&
                      Object.entries(work.plugin_metadata).map(([k, v]) => v != null && v !== '' ? (
                        <MetaRow key={k} label={k}>
                          <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{String(v)}</span>
                        </MetaRow>
                      ) : null)
                    }
                  </tbody>
                </table>
              </div>

              {/* Chunks section */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                  <h4 style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {hasChunks ? `Chunks (${chunks.length})` : work.content_is_image ? 'Image' : 'Content'}
                  </h4>
                  {hasChunks && chunks.length > 1 && (
                    <button
                      onClick={() => allCollapsed
                        ? setCollapsedChunks(new Set())
                        : setCollapsedChunks(new Set(chunks.map(c => c.chunk_id)))
                      }
                      style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                    >
                      {allCollapsed ? 'Expand all' : 'Collapse all'}
                    </button>
                  )}
                </div>

                {chunksLoading && <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading chunks…</p>}

                {hasChunks ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {chunks.map(chunk => (
                      <ChunkBlock
                        key={chunk.chunk_id}
                        chunk={chunk}
                        work={work}
                        dimensions={dimensions}
                        projectId={projectId}
                        collapsed={collapsedChunks.has(chunk.chunk_id)}
                        onToggleCollapse={() => toggleChunk(chunk.chunk_id)}
                      />
                    ))}
                  </div>
                ) : !chunksLoading && (
                  work.content_is_image && work.content ? (
                    <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 8 }}>
                      <img src={`data:image/jpeg;base64,${work.content}`} alt={work.work_title ?? 'image'} style={{ maxWidth: '100%', maxHeight: 'clamp(200px, 40vh, 480px)', objectFit: 'contain', borderRadius: 4 }} />
                    </div>
                  ) : work.content ? (
                    <div style={{
                      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6,
                      padding: '12px 16px', maxHeight: 'clamp(180px, 35vh, 400px)', overflowY: 'auto',
                      fontSize: 14, lineHeight: 1.75, whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word', overflowWrap: 'anywhere',
                      fontFamily: 'Georgia, serif',
                    }}>
                      {work.content}
                    </div>
                  ) : (
                    <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>(No content)</p>
                  )
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        {onRemove && (
          <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={() => {
                if (confirm('Remove this work? Associated chunks and ratings will also be deleted.')) {
                  onRemove(workRef)
                }
              }}
              style={{ background: 'none', border: '1px solid #c00', color: '#c00', borderRadius: 4, padding: '5px 14px', fontSize: 13, cursor: 'pointer' }}
            >
              Remove work
            </button>
          </div>
        )}
      </div>
    </div>
  )
}


function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '4px 12px 4px 0', color: 'var(--text-muted)', fontWeight: 500, whiteSpace: 'nowrap', verticalAlign: 'top' }}>{label}</td>
      <td style={{ padding: '4px 0' }}>{children}</td>
    </tr>
  )
}

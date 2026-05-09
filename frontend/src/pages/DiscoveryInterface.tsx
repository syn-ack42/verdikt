import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import DiscoveryAnalysisModal from '../components/DiscoveryAnalysisModal'
import { useIsMobile } from '../hooks/useIsMobile'

const PREFERENCE_OPTIONS = [
  { value: -2, label: 'Strongly avoid' },
  { value: -1, label: 'Avoid' },
  { value:  0, label: 'Neutral' },
  { value:  1, label: 'Seek' },
  { value:  2, label: 'Strongly seek' },
] as const

export default function DiscoveryInterface() {
  const isMobile = useIsMobile()
  const { projectId } = useParams<{ projectId: string }>()!
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [preference, setPreference] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [showAnalysis, setShowAnalysis] = useState(false)
  const reasonRef = useRef<HTMLTextAreaElement>(null)

  const nextKey = ['discovery', 'next', projectId] as const

  const { data, isLoading, error } = useQuery({
    queryKey: nextKey,
    queryFn: () => api.discovery.next(projectId!),
    retry: false,
    refetchOnWindowFocus: false,
  })

  const { data: status } = useQuery({
    queryKey: ['discovery-status', projectId],
    queryFn: () => api.discovery.status(projectId!),
    refetchInterval: (query) => query.state.data?.analysis?.running ? 2000 : false,
  })

  // Show reason box when preference is non-zero and non-null
  useEffect(() => {
    if (preference !== null && preference !== 0) {
      setTimeout(() => reasonRef.current?.focus(), 50)
    }
  }, [preference])

  const handleSkip = () => {
    if (submitting) return
    // Skip = "not now" — don't record, just advance to the next chunk
    qc.invalidateQueries({ queryKey: nextKey })
    setPreference(null)
    setReason('')
  }

  // Keyboard shortcuts: 1–5 → preference levels, Enter → submit, s → skip
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement) return
      if (e.key === '1') { setPreference(-2); setReason('') }
      else if (e.key === '2') { setPreference(-1); setReason('') }
      else if (e.key === '3') { setPreference(0); setReason('') }
      else if (e.key === '4') { setPreference(1); setReason('') }
      else if (e.key === '5') { setPreference(2); setReason('') }
      else if (e.key === 's') handleSkip()
      else if (e.key === 'Enter' && preference !== null) handleSubmit(preference)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const handleSubmit = async (pref: number) => {
    if (!data || submitting) return
    setSubmitting(true)
    try {
      await api.discovery.submitRating(projectId!, {
        chunk_id: data.chunk.id,
        material_item_id: data.material_item.id!,
        preference: pref,
        reason: reason.trim() || undefined,
      })
      qc.invalidateQueries({ queryKey: ['discovery-status', projectId] })
      qc.invalidateQueries({ queryKey: nextKey })
      setPreference(null)
      setReason('')
    } finally {
      setSubmitting(false)
    }
  }

  const chunk = data?.chunk
  const material = data?.material_item
  const liked = status?.liked ?? 0
  const disliked = status?.disliked ?? 0
  const total = status?.total ?? 0
  const ready = status?.ready ?? false
  const analysisStatus = status?.analysis ?? null

  const maxWidth = isMobile ? '100%' : 720

  return (
    <div style={{ maxWidth, margin: '0 auto', padding: isMobile ? '12px 12px 80px' : '24px 20px 80px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 14, padding: 0 }}
        >
          ← Back
        </button>
        <h2 style={{ margin: 0, fontSize: 18, flex: 1 }}>Discover Dimensions</h2>
        {total > 0 && (
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {total} rated · {liked}♥ {disliked}✗
          </span>
        )}
      </div>

      {/* Instruction */}
      <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 0, marginBottom: 20 }}>
        React to each sample — after enough liked and disliked reactions, Verdikt will suggest rating dimensions that reflect what matters to you.
      </p>

      {/* Chunk display */}
      {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}

      {error && (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
          {(error as { status?: number }).status === 404
            ? 'No more chunks available — all chunks in this project have been discovery-rated.'
            : 'Failed to load next chunk.'}
        </div>
      )}

      {chunk && (
        <>
          {/* Work info */}
          {material?.work_title && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
              {material.work_title}{material.author && ` — ${material.author}`}
            </div>
          )}

          {/* Content */}
          <div style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 16,
            marginBottom: 16,
            maxHeight: 400,
            overflowY: 'auto',
          }}>
            {chunk.domain === 'image' && chunk.content ? (
              <img
                src={`data:image/jpeg;base64,${chunk.content}`}
                alt="chunk"
                style={{ maxWidth: '100%', maxHeight: 360, objectFit: 'contain', display: 'block', margin: '0 auto' }}
              />
            ) : (
              <p style={{ margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: 15 }}>
                {chunk.content}
              </p>
            )}
          </div>

          {/* Description caption */}
          {chunk.description && (
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: -8, marginBottom: 16, fontStyle: 'italic' }}>
              {chunk.description}
            </p>
          )}

          {/* Preference selector */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            {PREFERENCE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => { setPreference(opt.value); if (opt.value === 0) setReason('') }}
                style={{
                  flex: 1,
                  minWidth: isMobile ? 60 : 80,
                  padding: '8px 4px',
                  fontSize: 13,
                  fontWeight: preference === opt.value ? 700 : 400,
                  background: preference === opt.value
                    ? (opt.value > 0 ? '#2e7d32' : opt.value < 0 ? '#c00' : 'var(--text-muted)')
                    : 'var(--card-bg)',
                  color: preference === opt.value ? '#fff' : 'var(--text)',
                  border: `1px solid ${preference === opt.value
                    ? (opt.value > 0 ? '#2e7d32' : opt.value < 0 ? '#c00' : 'var(--text-muted)')
                    : 'var(--border)'}`,
                  borderRadius: 6,
                  cursor: 'pointer',
                  transition: 'all 0.1s',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Reason textarea */}
          {preference !== null && preference !== 0 && (
            <textarea
              ref={reasonRef}
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="Why? (optional)"
              rows={2}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                marginBottom: 12,
                fontSize: 14,
                padding: '8px 10px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: 'var(--card-bg)',
                color: 'var(--text)',
                resize: 'vertical',
              }}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  if (preference !== null) handleSubmit(preference)
                }
              }}
            />
          )}

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              onClick={handleSkip}
              disabled={submitting}
              style={{ flex: 1, padding: '10px 0', fontSize: 14, cursor: 'pointer', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg)', color: 'var(--text-muted)' }}
            >
              Skip
            </button>
            <button
              onClick={() => { if (preference !== null) handleSubmit(preference) }}
              disabled={preference === null || submitting}
              style={{
                flex: 2,
                padding: '10px 0',
                fontSize: 14,
                fontWeight: 600,
                cursor: preference === null ? 'default' : 'pointer',
                borderRadius: 6,
                border: 'none',
                background: preference === null ? 'rgba(128,128,128,0.15)' : '#6b7de0',
                color: preference === null ? 'var(--text-muted)' : '#fff',
                opacity: submitting ? 0.6 : 1,
              }}
            >
              Submit
            </button>
          </div>

          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, textAlign: 'center' }}>
            Keys: 1–5 to select · Enter to submit · S to skip (resurfaces later)
          </p>
        </>
      )}

      {/* Analysis running indicator */}
      {analysisStatus?.running && (
        <div style={{ marginTop: 24, padding: '12px 16px', background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {analysisStatus.phase === 'describing'
                ? `Describing chunks (${analysisStatus.done} / ${analysisStatus.total})…`
                : analysisStatus.phase === 'synthesising'
                ? 'Synthesising dimensions…'
                : 'Preparing…'}
            </span>
            <button
              onClick={() => setShowAnalysis(true)}
              style={{ fontSize: 12, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'none', cursor: 'pointer' }}
            >
              Details
            </button>
          </div>
          <div style={{ background: 'var(--border)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
            <div style={{
              background: '#6b7de0',
              height: '100%',
              width: `${analysisStatus.total > 0 ? Math.round((analysisStatus.done / analysisStatus.total) * 100) : 5}%`,
              transition: 'width 0.5s',
            }} />
          </div>
        </div>
      )}

      {/* Result ready indicator */}
      {analysisStatus?.result && (analysisStatus.result.proposed_dimensions.length > 0 || (analysisStatus.result.irrelevant_existing?.length ?? 0) > 0) && !analysisStatus.running && (
        <div style={{ marginTop: 24, textAlign: 'center' }}>
          <button
            onClick={() => setShowAnalysis(true)}
            style={{ padding: '12px 28px', fontSize: 15, fontWeight: 600, background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}
          >
            Review proposed dimensions →
          </button>
        </div>
      )}

      {/* Error / empty-result state with retry */}
      {!analysisStatus?.running && (analysisStatus?.error || (analysisStatus?.result && analysisStatus.result.proposed_dimensions.length === 0 && (analysisStatus.result.irrelevant_existing?.length ?? 0) === 0)) && (
        <div style={{ marginTop: 24, padding: '12px 16px', background: 'var(--card-bg)', border: '1px solid #c00', borderRadius: 8 }}>
          <p style={{ margin: '0 0 10px', fontSize: 13, color: '#c00' }}>
            {analysisStatus?.error ?? 'Analysis returned no dimensions. Try rating more samples with strong reactions.'}
          </p>
          <button
            onClick={async () => {
              await api.discovery.clearAnalysisResult(projectId!)
              await api.discovery.startAnalysis(projectId!)
              qc.invalidateQueries({ queryKey: ['discovery-status', projectId] })
            }}
            style={{ padding: '6px 16px', fontSize: 13, fontWeight: 600, background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            Retry analysis
          </button>
        </div>
      )}

      {/* Analyse button */}
      {ready && !analysisStatus?.running && !analysisStatus?.result && !analysisStatus?.error && (
        <div style={{ marginTop: 32, textAlign: 'center' }}>
          <button
            onClick={async () => {
              await api.discovery.startAnalysis(projectId!)
              qc.invalidateQueries({ queryKey: ['discovery-status', projectId] })
              setShowAnalysis(true)
            }}
            style={{
              padding: '12px 28px',
              fontSize: 15,
              fontWeight: 600,
              background: '#6b7de0',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
            }}
          >
            Analyse preferences →
          </button>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 8 }}>
            {liked} liked · {disliked} disliked — enough to suggest dimensions
          </p>
        </div>
      )}

      {!ready && total > 0 && (
        <p style={{ marginTop: 24, fontSize: 13, color: 'var(--text-muted)', textAlign: 'center' }}>
          Need at least 5 liked and 5 disliked reactions to analyse.
          Currently: {liked} liked, {disliked} disliked.
        </p>
      )}

      {showAnalysis && analysisStatus && (
        <DiscoveryAnalysisModal
          projectId={projectId!}
          analysisStatus={analysisStatus}
          onClose={() => setShowAnalysis(false)}
          onApplied={() => {
            setShowAnalysis(false)
            navigate(`/projects/${projectId}`)
          }}
        />
      )}
    </div>
  )
}

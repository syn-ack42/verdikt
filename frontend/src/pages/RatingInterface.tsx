import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import RatingSlider from '../components/RatingSlider'
import { useIsMobile } from '../hooks/useIsMobile'

export default function RatingInterface() {
  const isMobile = useIsMobile()
  const { projectId } = useParams<{ projectId: string }>()!
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const [scores, setScores] = useState<Record<string, number>>({})
  const [activeIdx, setActiveIdx] = useState(0)
  const [mode, setMode] = useState<'normal' | 'confirm_ai'>(
    searchParams.get('mode') === 'confirm_ai' ? 'confirm_ai' : 'normal'
  )
  const aiOriginalScores = useRef<Record<string, number>>({})
  const chunkBoxRef = useRef<HTMLDivElement>(null)
  const [explExpanded, setExplExpanded] = useState(false)

  // Background AI preview state (normal mode only)
  const abortRef = useRef<AbortController | null>(null)
  const [aiPreview, setAiPreview] = useState<{
    ai_rating_id: string
    dimension_scores: Record<string, number>
    explanations: Record<string, string>
  } | null>(null)
  const [aiFlash, setAiFlash] = useState<{
    aiScores: Record<string, number>
    userScores: Record<string, number>
    explanations: Record<string, string>
  } | null>(null)

  const nextKey = ['ratings', projectId, 'next', mode] as const

  const { data, isLoading, error } = useQuery({
    queryKey: nextKey,
    queryFn: () => api.ratings.next(projectId!, mode),
    retry: false,
    refetchOnWindowFocus: false,
  })

  const { data: project } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId!),
  })

  const { data: appConfig } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.config.get(),
    staleTime: Infinity,
  })

  const dims = project?.rating_dimensions ?? []

  const prefetchNext = () => {
    qc.prefetchQuery({
      queryKey: nextKey,
      queryFn: () => api.ratings.next(projectId!, mode),
    })
  }

  const submit = useMutation({
    mutationFn: (opts: { skipped?: boolean; reason?: string }) => {
      // Cancel background AI preview and capture result before clearing
      abortRef.current?.abort()
      abortRef.current = null
      const capturedAi = aiPreview
      const capturedUserScores = { ...scores }
      setAiPreview(null)

      if (mode === 'confirm_ai' && data?.ai_rating_id && !opts.skipped) {
        // Restore original float for any dim the user didn't change
        const orig = aiOriginalScores.current
        const finalScores = Object.fromEntries(
          Object.entries(scores).map(([k, v]) =>
            [k, orig[k] !== undefined && Math.round(orig[k]) === v ? orig[k] : v]
          )
        )
        return api.ratings.updateRating(projectId!, data.ai_rating_id, finalScores)
      }

      // Show flash if we have a background AI result
      if (capturedAi && !opts.skipped) {
        setAiFlash({ aiScores: capturedAi.dimension_scores, userScores: capturedUserScores, explanations: capturedAi.explanations })
        setTimeout(() => setAiFlash(null), 5000)
      }

      return api.ratings.submit(projectId!, {
        chunk_id: data!.chunk.id,
        material_item_id: data!.material_item.id!,
        dimension_scores: opts.skipped ? {} : scores,
        skipped: opts.skipped ?? false,
        skip_reason: opts.reason,
        ai_rating_id: (!opts.skipped && capturedAi) ? capturedAi.ai_rating_id : undefined,
      })
    },
    onMutate: prefetchNext,
    onSuccess: () => {
      setScores({})
      setActiveIdx(0)
      qc.invalidateQueries({ queryKey: nextKey })
    },
  })

  // Background AI preview when a new chunk loads in normal mode
  useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setAiPreview(null)
    const previewEnabled = project?.domain === 'image' ? appConfig?.ai_preview_image : appConfig?.ai_preview_text
    if (mode !== 'normal' || !data || !projectId || !data.material_item.id || previewEnabled === false) return
    const ctrl = new AbortController()
    abortRef.current = ctrl
    api.ratings.aiPreview(projectId, data.chunk.id, data.material_item.id, ctrl.signal)
      .then(result => { if (!ctrl.signal.aborted) setAiPreview(result) })
      .catch(() => {})
    return () => { ctrl.abort() }
  }, [data?.chunk.id, mode, projectId, project?.domain, appConfig?.ai_preview_text, appConfig?.ai_preview_image])

  // Pre-fill scores from AI rating when in confirm mode
  useEffect(() => {
    if (mode === 'confirm_ai' && data?.prefilled_scores && Object.keys(data.prefilled_scores).length > 0) {
      aiOriginalScores.current = data.prefilled_scores
      // Round to nearest integer so slider buttons highlight correctly
      setScores(Object.fromEntries(
        Object.entries(data.prefilled_scores).map(([k, v]) => [k, Math.round(v)])
      ))
    } else {
      aiOriginalScores.current = {}
      setScores({})
    }
    setExplExpanded(false)
  }, [data?.chunk?.id, data?.ai_rating_id, mode])

  const allScored = dims.length > 0 && dims.every(d => scores[d.name] !== undefined)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (!data || !project) return
      const key = e.key

      if (key >= '1' && key <= '5') {
        const dim = dims[activeIdx]
        if (dim) setScores(s => ({ ...s, [dim.name]: Number(key) }))
      } else if (key === 'Tab') {
        e.preventDefault()
        setActiveIdx(i => e.shiftKey ? (i - 1 + dims.length) % dims.length : (i + 1) % dims.length)
      } else if (key === 'ArrowRight') {
        setActiveIdx(i => (i + 1) % dims.length)
      } else if (key === 'ArrowLeft') {
        setActiveIdx(i => (i - 1 + dims.length) % dims.length)
      } else if (key === 'Enter' && allScored) {
        submit.mutate({})
      } else if (key === 's') {
        submit.mutate({ skipped: true, reason: 'skipped' })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [data, project, dims, activeIdx, allScored, scores, submit])

  useEffect(() => {
    if (data?.chunk.id) {
      window.scrollTo(0, 0)
      if (chunkBoxRef.current) chunkBoxRef.current.scrollTop = 0
    }
  }, [data?.chunk.id])

  if (isLoading) return <p style={{ padding: 24 }}>Loading…</p>

  if (error || !data) {
    const status = (error as any)?.status
    const detail = (error as any)?.message
    const noAiChunks = mode === 'confirm_ai' && (status === 404 || detail === 'no_ai_chunks')
    return (
      <div style={{ maxWidth: 700, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
        <Link to={`/projects/${projectId}`}>← Dashboard</Link>
        <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
          {(['normal', 'confirm_ai'] as const).map(m => (
            <button
              key={m}
              onClick={() => { setMode(m); setScores({}); setActiveIdx(0) }}
              style={{
                padding: '6px 14px', borderRadius: 4, fontSize: 13, cursor: 'pointer',
                background: mode === m ? '#6b7de0' : 'none',
                color: mode === m ? '#fff' : 'inherit',
                border: mode === m ? 'none' : '1px solid var(--border)',
              }}
            >
              {m === 'normal' ? 'Rate new chunks' : 'Confirm AI ratings'}
            </button>
          ))}
        </div>
        <p style={{ marginTop: 16 }}>
          {noAiChunks
            ? 'All AI ratings confirmed. Start AI Rating from the dashboard to score more chunks.'
            : status === 404
            ? 'No unrated chunks available. Run the pipeline to generate chunks.'
            : 'Error loading next chunk.'}
        </p>
      </div>
    )
  }

  const { chunk, material_item, total_rated, total_chunks } = data

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <button onClick={() => navigate(`/projects/${projectId}`)} style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
          ← Dashboard
        </button>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          {total_rated} / {total_chunks} rated
        </span>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {(['normal', 'confirm_ai'] as const).map(m => (
          <button
            key={m}
            onClick={() => { setMode(m); setScores({}); setActiveIdx(0) }}
            style={{
              padding: '5px 12px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
              background: mode === m ? '#6b7de0' : 'none',
              color: mode === m ? '#fff' : 'inherit',
              border: mode === m ? 'none' : '1px solid var(--border)',
            }}
          >
            {m === 'normal' ? 'Rate new chunks' : 'Confirm AI ratings'}
          </button>
        ))}
      </div>

      <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--text-muted)' }}>
        {material_item.work_title ?? material_item.source_path?.split('/').pop() ?? 'Unknown'}
        {material_item.author && ` — ${material_item.author}`}
        {' · '}cluster {chunk.cluster_id ?? '—'} · position {chunk.position}
      </div>

      {chunk.description && (
        <div style={{ marginBottom: 10, fontSize: 12, borderRadius: 6, background: 'rgba(107,125,224,0.06)', border: '1px solid rgba(107,125,224,0.13)', padding: '6px 10px', lineHeight: 1.5, color: 'var(--text)' }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: '#6b7de0', marginRight: 6, letterSpacing: '0.05em' }}>AI</span>
          {chunk.description}
        </div>
      )}

      <div ref={chunkBoxRef} style={{
        background: 'var(--chunk-bg)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        marginBottom: 16,
        ...(chunk.domain === 'image'
          ? { display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 8, maxHeight: 'clamp(200px, 50vh, 520px)', overflow: 'hidden' }
          : { padding: '12px 16px', lineHeight: 1.7, fontSize: 14, whiteSpace: 'pre-wrap', fontFamily: 'Georgia, serif', maxHeight: 'clamp(150px, 35vh, 320px)', overflowY: 'auto' }
        ),
      }}>
        {chunk.domain === 'image' && chunk.content
          ? <img src={`data:image/jpeg;base64,${chunk.content}`} alt={material_item.work_title ?? 'image'} style={{ maxWidth: '100%', maxHeight: 'clamp(200px, 50vh, 500px)', objectFit: 'contain', borderRadius: 4 }} />
          : chunk.content ?? '(no content)'
        }
      </div>

      {mode === 'confirm_ai' && data?.ai_explanations && Object.keys(data.ai_explanations).length > 0 && (
        <div
          onClick={() => setExplExpanded(v => !v)}
          style={{ marginBottom: 12, borderRadius: 6, background: 'var(--surface, rgba(128,128,128,0.06))', padding: '6px 12px', cursor: 'pointer', fontSize: 12, color: 'var(--text-muted)' }}
        >
          {explExpanded ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(data.ai_explanations).map(([k, v]) => (
                <div key={k}><span style={{ fontWeight: 600, color: 'var(--text)' }}>{k}:</span> {v}</div>
              ))}
              <span style={{ fontSize: 11, marginTop: 2 }}>▴ collapse</span>
            </div>
          ) : (
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              <span style={{ marginRight: 6, fontSize: 11 }}>▾</span>
              {Object.entries(data.ai_explanations).map(([k, v]) => `${k}: ${v}`).join(' · ')}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: 4, marginBottom: 16 }}>
        {dims.map((dim, i) => (
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

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={() => submit.mutate({})}
          disabled={!allScored || submit.isPending}
          style={{ background: allScored ? '#6b7de0' : 'var(--border)', color: allScored ? '#fff' : 'var(--text-muted)', border: 'none', padding: '8px 20px', borderRadius: 4, cursor: allScored ? 'pointer' : 'default' }}
        >
          Submit (Enter)
        </button>
        <button
          onClick={() => submit.mutate({ skipped: true, reason: 'skipped' })}
          disabled={submit.isPending}
          style={{ padding: '8px 16px', borderRadius: 4 }}
        >
          Skip (s)
        </button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
          Tab/→ next dim · 1–5 score · Enter submit
        </span>
        {mode === 'normal' && aiPreview && !submit.isPending && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>● AI ready</span>
        )}
      </div>

      {aiFlash && (
        <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(107,125,224,0.07)', border: '1px solid rgba(107,125,224,0.18)', fontSize: 12 }}>
          <span style={{ color: 'var(--text-muted)', marginRight: 6 }}>AI would have rated:</span>
          {dims.map(d => {
            const ai = aiFlash.aiScores[d.name]
            const user = aiFlash.userScores[d.name]
            const diff = ai !== undefined && user !== undefined ? user - ai : null
            return (
              <span key={d.name} style={{ marginRight: 10 }}>
                {d.name}: <strong>{ai?.toFixed(1) ?? '—'}</strong>
                {diff !== null && (
                  <span style={{ marginLeft: 2, color: Math.abs(diff) <= 0.5 ? '#2e7d32' : '#b45309' }}>
                    ({diff > 0 ? '+' : ''}{diff.toFixed(1)})
                  </span>
                )}
              </span>
            )
          })}
          {(() => {
            const dims2 = Object.keys(aiFlash.aiScores)
            const agreements = dims2
              .filter(d => aiFlash.userScores[d] !== undefined)
              .map(d => 1 - Math.abs((aiFlash.aiScores[d] ?? 0) - (aiFlash.userScores[d] ?? 0)) / 4)
            const avg = agreements.length > 0 ? agreements.reduce((a, b) => a + b, 0) / agreements.length : null
            return avg !== null ? (
              <span style={{ marginLeft: 4, color: 'var(--text-muted)' }}>· {Math.round(avg * 100)}% match</span>
            ) : null
          })()}
        </div>
      )}
    </div>
  )
}


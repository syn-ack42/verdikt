import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import RatingSlider from '../components/RatingSlider'

export default function RatingInterface() {
  const { projectId } = useParams<{ projectId: string }>()!
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [scores, setScores] = useState<Record<string, number>>({})
  const [activeIdx, setActiveIdx] = useState(0)

  const nextKey = ['ratings', projectId, 'next'] as const

  const { data, isLoading, error } = useQuery({
    queryKey: nextKey,
    queryFn: () => api.ratings.next(projectId!),
    retry: false,
  })

  const { data: project } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId!),
  })

  const dims = project?.rating_dimensions ?? []

  const prefetchNext = () => {
    qc.prefetchQuery({
      queryKey: nextKey,
      queryFn: () => api.ratings.next(projectId!),
    })
  }

  const submit = useMutation({
    mutationFn: (opts: { skipped?: boolean; reason?: string }) =>
      api.ratings.submit(projectId!, {
        chunk_id: data!.chunk.id,
        material_item_id: data!.material_item.id!,
        dimension_scores: opts.skipped ? {} : scores,
        skipped: opts.skipped ?? false,
        skip_reason: opts.reason,
      }),
    onMutate: prefetchNext,
    onSuccess: () => {
      setScores({})
      setActiveIdx(0)
      qc.invalidateQueries({ queryKey: nextKey })
    },
  })

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

  if (isLoading) return <p style={{ padding: 24 }}>Loading…</p>

  if (error || !data) {
    const status = (error as any)?.status
    return (
      <div style={{ maxWidth: 700, margin: '0 auto', padding: 24 }}>
        <Link to={`/projects/${projectId}`}>← Dashboard</Link>
        <p style={{ marginTop: 24 }}>
          {status === 404
            ? 'No unrated chunks available. Run the pipeline to generate chunks.'
            : 'Error loading next chunk.'}
        </p>
      </div>
    )
  }

  const { chunk, material_item, total_rated, total_chunks } = data

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <button onClick={() => navigate(`/projects/${projectId}`)} style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
          ← Dashboard
        </button>
        <span style={{ fontSize: 13, color: '#888' }}>
          {total_rated} / {total_chunks} rated
        </span>
      </div>

      <div style={{ marginBottom: 8, fontSize: 12, color: '#999' }}>
        {material_item.work_title ?? material_item.source_path?.split('/').pop() ?? 'Unknown'}
        {material_item.author && ` — ${material_item.author}`}
        {' · '}cluster {chunk.cluster_id ?? '—'} · position {chunk.position}
      </div>

      <div style={{
        background: '#fafafa',
        border: '1px solid #e0e0e0',
        borderRadius: 8,
        padding: 20,
        marginBottom: 20,
        lineHeight: 1.7,
        maxWidth: '65ch',
        fontSize: 15,
        whiteSpace: 'pre-wrap',
      }}>
        {chunk.content ?? '(binary content)'}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 20 }}>
        {dims.map((dim, i) => (
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

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          onClick={() => submit.mutate({})}
          disabled={!allScored || submit.isPending}
          style={{ background: allScored ? '#6b7de0' : '#ccc', color: '#fff', border: 'none', padding: '8px 20px', borderRadius: 4, cursor: allScored ? 'pointer' : 'default' }}
        >
          Submit (Enter)
        </button>
        <button
          onClick={() => submit.mutate({ skipped: true, reason: 'skipped' })}
          disabled={submit.isPending}
          style={{ background: 'none', border: '1px solid #ccc', padding: '8px 16px', borderRadius: 4 }}
        >
          Skip (s)
        </button>
        <span style={{ fontSize: 12, color: '#aaa', marginLeft: 8 }}>
          Tab/→ next dim · 1–5 score · Enter submit
        </span>
      </div>
    </div>
  )
}


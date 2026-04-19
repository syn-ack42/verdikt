import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DimensionProfile } from '../api/types'

const CRYSTALLISE_MESSAGES = [
  'Analysing your ratings…',
  'Building dimension profiles…',
  'Comparing high and low scores…',
  'Synthesising your preferences…',
  'Generating dimension summaries…',
  'Writing overall profile…',
  'Almost there…',
]

function CrystalliseProgress() {
  const [pos, setPos] = useState(0)
  const [msgIndex, setMsgIndex] = useState(0)
  const msgTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const bar = setInterval(() => setPos(p => (p + 0.004) % 1), 16)
    const scheduleNext = (idx: number) => {
      const delay = 2500 + Math.random() * 1500
      msgTimer.current = setTimeout(() => {
        const next = (idx + 1) % CRYSTALLISE_MESSAGES.length
        setMsgIndex(next)
        scheduleNext(next)
      }, delay)
    }
    scheduleNext(0)
    return () => {
      clearInterval(bar)
      if (msgTimer.current) clearTimeout(msgTimer.current)
    }
  }, [])

  const translateX = -100 + pos * 400

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ height: 3, background: '#e8eaff', borderRadius: 2, overflow: 'hidden', marginBottom: 10 }}>
        <div style={{
          height: '100%', width: '25%', background: '#6b7de0', borderRadius: 2,
          transform: `translateX(${translateX}%)`,
        }} />
      </div>
      <p style={{ margin: 0, fontSize: 13, color: '#6b7de0' }}>{CRYSTALLISE_MESSAGES[msgIndex]}</p>
    </div>
  )
}

export default function ProfileView() {
  const { projectId } = useParams<{ projectId: string }>()!
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile', projectId],
    queryFn: () => api.profile.get(projectId!),
    retry: false,
  })

  const { data: project } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId!),
  })

  const [editedDims, setEditedDims] = useState<DimensionProfile[] | null>(null)
  const [editedSummary, setEditedSummary] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  const crystallise = useMutation({
    mutationFn: () => api.profile.crystallise(projectId!),
    onSuccess: (p) => {
      qc.setQueryData(['profile', projectId], p)
      setEditedDims(null)
      setEditedSummary(null)
      setDirty(false)
    },
  })

  const save = useMutation({
    mutationFn: () => api.profile.update(projectId!, {
      overall_summary: editedSummary ?? profile!.overall_summary,
      dimensions: editedDims ?? profile!.dimensions,
    }),
    onSuccess: (p) => {
      qc.setQueryData(['profile', projectId], p)
      setDirty(false)
    },
  })

  if (isLoading) return <p style={{ padding: 24 }}>Loading…</p>

  const dims = editedDims ?? profile?.dimensions ?? []
  const summary = editedSummary ?? profile?.overall_summary ?? ''

  const updateDim = (i: number, patch: Partial<DimensionProfile>) => {
    const next = dims.map((d, idx) => idx === i ? { ...d, ...patch } : d)
    setEditedDims(next)
    setDirty(true)
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <button onClick={() => navigate(`/projects/${projectId}`)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0 }}>
            ← Dashboard
          </button>
          <h2 style={{ margin: '8px 0 0' }}>Preference Profile</h2>
          {profile && (
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#888' }}>
              v{profile.version} · {profile.rating_count} ratings
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {dirty && (
            <button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save edits'}
            </button>
          )}
          <button
            onClick={() => crystallise.mutate()}
            disabled={crystallise.isPending}
            style={{ background: '#6b7de0', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: 4 }}
          >
            {crystallise.isPending ? 'Crystallising…' : profile ? 'Re-crystallise' : 'Crystallise'}
          </button>
        </div>
      </div>

      {crystallise.error && (
        <div style={{ background: '#fff5f5', border: '1px solid #fca5a5', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
          <strong style={{ color: '#c00', fontSize: 13 }}>Crystallisation failed</strong>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#700' }}>
            {(crystallise.error as any)?.message ?? String(crystallise.error)}
          </p>
        </div>
      )}

      {crystallise.isPending && <CrystalliseProgress />}

      {!profile && !crystallise.isPending && (
        <div style={{ textAlign: 'center', padding: 48, color: '#888' }}>
          <p>No profile yet.</p>
          <p style={{ fontSize: 13 }}>
            Rate {project?.crystallisation_threshold ?? '?'} chunks then click Re-crystallise.
          </p>
        </div>
      )}

      {profile && (
        <>
          <div style={{ marginBottom: 24 }}>
            <h3>Overall</h3>
            <textarea
              value={summary}
              onChange={e => { setEditedSummary(e.target.value); setDirty(true) }}
              style={{ width: '100%', minHeight: 80, padding: 8, borderRadius: 4, border: '1px solid #ddd' }}
            />
          </div>

          <h3>Dimensions</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {dims.map((d, i) => (
              <div key={d.name} style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <strong>{d.name}</strong>
                  <span style={{ fontSize: 13, color: '#888' }}>avg {d.typical_score.toFixed(1)} / 5</span>
                </div>
                <textarea
                  value={d.summary}
                  onChange={e => updateDim(i, { summary: e.target.value })}
                  style={{ width: '100%', minHeight: 60, padding: 8, borderRadius: 4, border: '1px solid #ddd', fontSize: 13 }}
                />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

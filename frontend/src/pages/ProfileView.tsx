import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DimensionProfile, PreferenceProfile } from '../api/types'

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
      <div style={{ height: 3, background: 'var(--border)', borderRadius: 2, overflow: 'hidden', marginBottom: 10 }}>
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
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: profile, isLoading } = useQuery({
    queryKey: ['profile', projectId],
    queryFn: () => api.profile.get(projectId!),
    retry: false,
  })

  const { data: project } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId!),
  })

  const { data: versions } = useQuery({
    queryKey: ['profile-versions', projectId],
    queryFn: () => api.profile.versions(projectId!),
    enabled: !!projectId,
    retry: false,
  })

  const { data: crystalStatus } = useQuery({
    queryKey: ['crystallise-status', projectId],
    queryFn: () => api.profile.crystalliseStatus(projectId!),
    refetchInterval: (query) => query.state.data?.running ? 2000 : false,
    enabled: !!projectId,
  })

  const [editedDims, setEditedDims] = useState<DimensionProfile[] | null>(null)
  const [editedSummary, setEditedSummary] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [streamTokens, setStreamTokens] = useState<{ prompt: number; completion: number } | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [isStreamRunning, setIsStreamRunning] = useState(false)

  const startCrystalliseStream = async () => {
    setIsStreamRunning(true)
    setStreamError(null)
    setStreamTokens(null)
    try {
      await api.profile.crystalliseStream(projectId!, (e: unknown) => {
        const ev = e as { type: string; prompt?: number; completion?: number; profile?: PreferenceProfile; message?: string }
        if (ev.type === 'progress') {
          setStreamTokens({ prompt: ev.prompt ?? 0, completion: ev.completion ?? 0 })
        } else if (ev.type === 'done' && ev.profile) {
          qc.setQueryData(['profile', projectId], ev.profile)
          qc.invalidateQueries({ queryKey: ['profile-versions', projectId] })
          setEditedDims(null)
          setEditedSummary(null)
          setDirty(false)
        } else if (ev.type === 'error') {
          setStreamError(ev.message ?? 'Crystallisation failed')
        }
      })
    } catch (err: unknown) {
      setStreamError((err as Error).message ?? 'Crystallisation failed')
    } finally {
      setIsStreamRunning(false)
      setStreamTokens(null)
    }
  }

  const save = useMutation({
    mutationFn: () => api.profile.update(projectId!, {
      overall_summary: editedSummary ?? profile!.overall_summary,
      dimensions: editedDims ?? profile!.dimensions,
    }),
    onSuccess: (p) => {
      qc.setQueryData(['profile', projectId], p)
      qc.invalidateQueries({ queryKey: ['profile-versions', projectId] })
      setEditedDims(null)
      setEditedSummary(null)
      setDirty(false)
    },
  })

  const restore = useMutation({
    mutationFn: (versionId: string) => api.profile.restore(projectId!, versionId),
    onSuccess: (p) => {
      qc.setQueryData(['profile', projectId], p)
      qc.invalidateQueries({ queryKey: ['profile-versions', projectId] })
      setEditedDims(null)
      setEditedSummary(null)
      setDirty(false)
    },
  })

  // Detect server-side crystallization that outlasted our component (user navigated away and back)
  const serverRunning = !isStreamRunning && (crystalStatus?.running ?? false)
  const isCrystallising = isStreamRunning || serverRunning

  const prevServerRunning = useRef(false)
  useEffect(() => {
    if (prevServerRunning.current && !serverRunning) {
      qc.invalidateQueries({ queryKey: ['profile', projectId] })
      qc.invalidateQueries({ queryKey: ['profile-versions', projectId] })
    }
    prevServerRunning.current = serverRunning
  }, [serverRunning, projectId, qc])

  if (isLoading) return <p style={{ padding: 24 }}>Loading…</p>

  const dims = editedDims ?? profile?.dimensions ?? []
  const summary = editedSummary ?? profile?.overall_summary ?? ''

  const updateDim = (i: number, patch: Partial<DimensionProfile>) => {
    const next = dims.map((d, idx) => idx === i ? { ...d, ...patch } : d)
    setEditedDims(next)
    setDirty(true)
  }

  const handleCrystallise = () => {
    const nextVersion = (profile?.version ?? 0) + 1
    const parts = [
      profile ? `A new version (v${nextVersion}) will be created.` : null,
      dirty ? `Your unsaved manual edits will be discarded.` : null,
    ].filter(Boolean)
    if (parts.length > 0 && !confirm(parts.join('\n'))) return
    startCrystalliseStream()
  }

  const handleDownload = () => {
    if (!profile) return
    const safeName = (project?.name ?? 'profile')
      .replace(/[^a-zA-Z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
    const blob = new Blob([JSON.stringify(profile, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `profile_${safeName}_v${profile.version}_${profile.created_at.slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setImportError(null)
    const text = await file.text()
    let data: Partial<PreferenceProfile>
    try {
      data = JSON.parse(text)
    } catch {
      setImportError('Not a valid JSON file.')
      return
    }
    if (!data.overall_summary || !Array.isArray(data.dimensions)) {
      setImportError('File does not look like a profile export.')
      return
    }
    if (!confirm("Import this profile? It will overwrite the current version's content.")) return
    const updated = await api.profile.update(projectId!, {
      overall_summary: data.overall_summary,
      dimensions: data.dimensions,
    })
    qc.setQueryData(['profile', projectId], updated)
    setEditedDims(null)
    setEditedSummary(null)
    setDirty(false)
  }

  const btnBase: React.CSSProperties = {
    padding: '7px 14px', borderRadius: 4, fontSize: 14, cursor: 'pointer',
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <button
            onClick={() => navigate(`/projects/${projectId}`)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0 }}
          >
            ← Dashboard
          </button>
          <h2 style={{ margin: '8px 0 0' }}>Preference Profile</h2>
          {profile && (
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>
                v{profile.version} · {profile.rating_count} ratings · saved {profile.created_at.slice(0, 10)}
                {profile.confirmed_count > 0 && profile.profile_confidence !== null &&
                  ` · ${Math.round((profile.profile_confidence ?? 0) * 100)}% AI accuracy (${profile.confirmed_count} confirmations)`}
              </span>
              {versions && versions.length > 1 && (
                <button
                  onClick={() => setShowHistory(v => !v)}
                  style={{ fontSize: 11, color: showHistory ? '#6b7de0' : 'var(--text-muted)', background: 'none', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 6px', cursor: 'pointer' }}
                >
                  {showHistory ? '▴' : '▾'} {versions.length} versions
                </button>
              )}
            </p>
          )}
          {showHistory && versions && versions.length > 1 && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 480 }}>
              {versions.map(v => (
                <div
                  key={v.id}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '5px 10px', border: '1px solid var(--border)', borderRadius: 5,
                    background: v.id === profile?.id ? 'var(--surface)' : 'transparent',
                    fontSize: 12,
                  }}
                >
                  <span>
                    <strong>v{v.version}</strong>
                    <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                      {v.created_at.slice(0, 10)} · {v.rating_count} ratings
                      {v.confirmed_count > 0 && v.profile_confidence !== null &&
                        ` · ${Math.round((v.profile_confidence ?? 0) * 100)}% AI accuracy`}
                    </span>
                    {v.id === profile?.id && (
                      <span style={{ marginLeft: 8, color: '#6b7de0' }}>current</span>
                    )}
                  </span>
                  {v.id !== profile?.id && (
                    <button
                      onClick={() => confirm(`Restore v${v.version}? This creates a new version based on that content.`) && restore.mutate(v.id)}
                      disabled={restore.isPending}
                      style={{ fontSize: 11, color: '#6b7de0', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 6px' }}
                    >
                      Restore
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {profile && (
            <>
              <button
                onClick={handleDownload}
                style={{ ...btnBase, background: 'none', border: '1px solid var(--border)' }}
                title="Export profile as JSON"
              >
                ↓ Export
              </button>
              <button
                onClick={() => fileRef.current?.click()}
                style={{ ...btnBase, background: 'none', border: '1px solid var(--border)' }}
                title="Import profile from JSON"
              >
                ↑ Import
              </button>
              <input ref={fileRef} type="file" accept=".json" onChange={handleImport} style={{ display: 'none' }} />
            </>
          )}
          <button
            onClick={() => save.mutate()}
            disabled={!dirty || save.isPending}
            style={{
              ...btnBase,
              background: dirty ? '#6b7de0' : 'var(--border)',
              color: dirty ? '#fff' : 'var(--text-muted)',
              border: 'none',
              cursor: dirty ? 'pointer' : 'default',
            }}
          >
            {save.isPending ? 'Saving…' : 'Save edits'}
          </button>
          <button
            onClick={handleCrystallise}
            disabled={isCrystallising}
            style={{
              ...btnBase,
              background: isCrystallising ? 'var(--border)' : '#6b7de0',
              color: isCrystallising ? 'var(--text-muted)' : '#fff',
              border: 'none',
              cursor: isCrystallising ? 'default' : 'pointer',
            }}
          >
            {isCrystallising ? 'Crystallising…' : profile ? 'Re-crystallise' : 'Crystallise'}
          </button>
        </div>
      </div>

      {/* Error states */}
      {streamError && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
          <strong style={{ color: '#c00', fontSize: 13 }}>Crystallisation failed</strong>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{streamError}</p>
        </div>
      )}
      {importError && (
        <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
          <strong style={{ color: '#c00', fontSize: 13 }}>Import failed</strong>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{importError}</p>
        </div>
      )}

      {isCrystallising && (
        <>
          <CrystalliseProgress />
          {streamTokens && (
            <p style={{ margin: '-16px 0 16px', fontSize: 12, color: 'var(--text-muted)' }}>
              {streamTokens.prompt.toLocaleString()} prompt · {streamTokens.completion.toLocaleString()} completion tokens processed
            </p>
          )}
        </>
      )}

      {/* Empty state */}
      {!profile && !isCrystallising && (
        <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-muted)' }}>
          <p>No profile yet.</p>
          <p style={{ fontSize: 13 }}>
            Rate at least {project?.crystallisation_threshold ?? '?'} chunks then click Crystallise.
          </p>
        </div>
      )}

      {/* Profile content */}
      {profile && (
        <>
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ margin: '0 0 8px' }}>Overall summary</h3>
            <textarea
              value={summary}
              onChange={e => { setEditedSummary(e.target.value); setDirty(true) }}
              style={{
                width: '100%', minHeight: 80, padding: 8, borderRadius: 4,
                border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
                boxSizing: 'border-box', fontFamily: 'inherit', fontSize: 14, lineHeight: 1.6,
              }}
            />
          </div>

          <h3 style={{ margin: '0 0 12px' }}>Dimensions</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(380px, 100%), 1fr))', gap: 16, marginBottom: 32 }}>
            {dims.map((d, i) => (
              <div key={d.name} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <strong>{d.name}</strong>
                  <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>avg {d.typical_score.toFixed(1)} / 5</span>
                </div>
                <textarea
                  value={d.summary}
                  onChange={e => updateDim(i, { summary: e.target.value })}
                  style={{
                    width: '100%', minHeight: 80, padding: 8, borderRadius: 4,
                    border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
                    fontSize: 13, boxSizing: 'border-box', fontFamily: 'inherit', lineHeight: 1.6,
                  }}
                />
              </div>
            ))}
          </div>
        </>
      )}

    </div>
  )
}

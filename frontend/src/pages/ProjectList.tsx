import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../api/client'
import type { User } from '../api/types'
import StorageManager from '../components/StorageManager'
import { iconBtn } from '../styles'
import logoLight from '../assets/verdikt-icon-transparent-dark.svg'
import logoDark from '../assets/verdikt-icon-transparent-white.svg'

function ProjectJobBadges({ projectId }: { projectId: string }) {
  const { data: aiStatus } = useQuery({
    queryKey: ['ai-rating-status', projectId],
    queryFn: () => api.aiRating.status(projectId),
    refetchInterval: 8000,
  })
  const { data: updateStatus } = useQuery({
    queryKey: ['update-plugin-status', projectId],
    queryFn: () => api.works.getUpdateStatus(projectId),
    refetchInterval: 8000,
  })
  const { data: crystalliseStatus } = useQuery({
    queryKey: ['crystallise-status', projectId],
    queryFn: () => api.profile.crystalliseStatus(projectId),
    refetchInterval: 8000,
  })

  const badges: { label: string }[] = []
  if (aiStatus?.running) badges.push({ label: 'AI Rating' })
  if (updateStatus?.running) badges.push({ label: 'Updating' })
  if (crystalliseStatus?.running) badges.push({ label: 'Crystallising' })

  if (badges.length === 0) return null

  return (
    <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
      {badges.map(b => (
        <span key={b.label} style={{
          background: 'rgba(107,125,224,0.12)', color: '#6b7de0',
          fontSize: 10, padding: '2px 7px', borderRadius: 10, fontWeight: 600, letterSpacing: 0.2,
        }}>
          ● {b.label}
        </span>
      ))}
    </div>
  )
}

export default function ProjectList() {
  const { user } = useOutletContext<{ user: User }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: api.projects.list,
  })

  const handleLogout = async () => {
    await api.auth.logout()
    qc.clear()
    navigate('/login')
  }

  const [showSettingsMenu, setShowSettingsMenu] = useState(false)
  const [showStorageManager, setShowStorageManager] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importSuccess, setImportSuccess] = useState<string | null>(null)
  const settingsRef = useRef<HTMLDivElement>(null)
  const importRef = useRef<HTMLInputElement>(null)

  const handleImport = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setImportError(null)
    setImportSuccess(null)
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const result = await api.projects.importProject(data)
      setImportSuccess(`Imported "${data.project?.name ?? 'project'}" — ${result.materials_imported} works, ${result.ratings_imported} ratings.`)
      qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err: any) {
      setImportError(err?.message ?? 'Import failed')
    }
  }, [qc])

  useEffect(() => {
    if (!showSettingsMenu) return
    function handleClick(e: MouseEvent) {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setShowSettingsMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showSettingsMenu])

  if (isLoading) return <p>Loading…</p>

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <h1 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          <picture>
            <source srcSet={logoLight} media="(prefers-color-scheme: light)" />
            <img src={logoDark} alt="" width={52} height={52} style={{ display: 'block' }} />
          </picture>
          Verdikt
        </h1>
        <div ref={settingsRef} style={{ position: 'relative' }}>
          <button
            onClick={() => setShowSettingsMenu(v => !v)}
            title="Settings"
            style={{ ...iconBtn, border: '1px solid var(--border)' }}
          >☰</button>
          {showSettingsMenu && (
            <div style={{
              position: 'absolute', top: 'calc(100% + 6px)', right: 0,
              background: 'var(--bg, #1a1a1a)', border: '1px solid var(--border, #e0e0e0)',
              borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.18)',
              minWidth: 160, zIndex: 50, overflow: 'hidden',
            }}>
              <button
                onClick={() => { setShowSettingsMenu(false); setShowStorageManager(true) }}
                style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
              >
                Manage Files
              </button>
              <button
                onClick={() => { setShowSettingsMenu(false); navigate('/usage') }}
                style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
              >
                Token Usage
              </button>
              <button
                onClick={() => { setShowSettingsMenu(false); navigate('/settings/password') }}
                style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
              >
                Change Password
              </button>
              {user?.is_admin && (
                <>
                  <button
                    onClick={() => { setShowSettingsMenu(false); navigate('/admin/users') }}
                    style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                  >
                    Admin: Users
                  </button>
                  <button
                    onClick={() => { setShowSettingsMenu(false); navigate('/admin/models') }}
                    style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                  >
                    Admin: Models
                  </button>
                  <button
                    onClick={() => { setShowSettingsMenu(false); navigate('/admin/settings') }}
                    style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                  >
                    Admin: Settings
                  </button>
                </>
              )}
              <button
                onClick={() => { setShowSettingsMenu(false); handleLogout() }}
                style={{ width: '100%', padding: '10px 16px', textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, borderTop: '1px solid var(--border)', color: 'var(--text-muted)' }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
              >
                Sign out ({user?.email})
              </button>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginBottom: 24, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Link to="/projects/new"><button>New Project</button></Link>
        <button
          onClick={() => importRef.current?.click()}
          style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 14 }}
        >Import…</button>
        <input ref={importRef} type="file" accept=".json" style={{ display: 'none' }} onChange={handleImport} />
        {importSuccess && <span style={{ fontSize: 13, color: '#2e7d32' }}>{importSuccess}</span>}
        {importError && <span style={{ fontSize: 13, color: '#c00' }}>{importError}</span>}
      </div>

      {!projects?.length && <p style={{ color: '#888' }}>No projects yet. Create one to get started.</p>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {projects?.map(p => (
          <div key={p.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minWidth: 0 }}>
              <Link to={`/projects/${p.id}`} style={{ textDecoration: 'none', color: 'inherit', flex: 1 }}>
                <h3 style={{ margin: '0 0 4px' }}>{p.name}</h3>
                {p.description && <p style={{ margin: '0 0 6px', color: 'var(--text-muted)', fontSize: 14 }}>{p.description}</p>}
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {p.domain} · {p.rating_dimensions.length} dimensions · created {p.created_at.slice(0, 10)}
                </span>
                <ProjectJobBadges projectId={p.id} />
              </Link>
              <Link to={`/projects/${p.id}`}>
                <button style={{ ...iconBtn, fontSize: '1.3em', color: 'var(--text-muted, #aaa)' }}>›</button>
              </Link>
            </div>
          </div>
        ))}
      </div>

      {showStorageManager && (
        <StorageManager onClose={() => setShowStorageManager(false)} />
      )}
    </div>
  )
}

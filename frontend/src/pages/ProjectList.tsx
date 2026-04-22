import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import StorageManager from '../components/StorageManager'
import { iconBtn } from '../styles'

export default function ProjectList() {
  const qc = useQueryClient()
  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: api.projects.list,
  })

  const del = useMutation({
    mutationFn: (id: string) => api.projects.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })

  const [showSettingsMenu, setShowSettingsMenu] = useState(false)
  const [showStorageManager, setShowStorageManager] = useState(false)
  const settingsRef = useRef<HTMLDivElement>(null)

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
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <h1 style={{ margin: 0 }}>Verdikt</h1>
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
                style={{
                  width: '100%', padding: '10px 16px', textAlign: 'left',
                  background: 'none', border: 'none', cursor: 'pointer', fontSize: 14,
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface, rgba(255,255,255,0.06))')}
                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
              >
                Manage Files
              </button>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginBottom: 24 }}>
        <Link to="/projects/new"><button>New Project</button></Link>
      </div>

      {!projects?.length && <p style={{ color: '#888' }}>No projects yet. Create one to get started.</p>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {projects?.map(p => (
          <div key={p.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16, minWidth: 480 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minWidth: 0 }}>
              <Link to={`/projects/${p.id}`} style={{ textDecoration: 'none', color: 'inherit', flex: 1 }}>
                <h3 style={{ margin: '0 0 4px' }}>{p.name}</h3>
                {p.description && <p style={{ margin: '0 0 6px', color: 'var(--text-muted)', fontSize: 14 }}>{p.description}</p>}
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {p.domain} · {p.rating_dimensions.length} dimensions · created {p.created_at.slice(0, 10)}
                </span>
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

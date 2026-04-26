import { useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ModelCatalogEntry, User } from '../api/types'

const TYPE_LABELS: Record<string, string> = { llm: 'LLM', embedding: 'Embedding' }
const DOMAIN_LABELS: Record<string, string> = { text: 'Text', image: 'Image', any: 'Any' }

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: `${color}22`, color, fontWeight: 600, letterSpacing: 0.3 }}>
      {label}
    </span>
  )
}

export default function AdminModels() {
  const { user: me } = useOutletContext<{ user: User }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<ModelCatalogEntry | null>(null)
  const [editForm, setEditForm] = useState<Partial<ModelCatalogEntry>>({})

  if (!me.is_admin) return <div style={{ padding: 24 }}>Access denied.</div>

  const { data: models, isLoading } = useQuery({
    queryKey: ['admin-models'],
    queryFn: () => api.admin.listModels(),
  })

  const sync = useMutation({
    mutationFn: () => api.admin.syncModels(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-models'] }),
  })

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<ModelCatalogEntry> }) =>
      api.admin.updateModel(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-models'] })
      setEditing(null)
    },
  })

  const openEdit = (m: ModelCatalogEntry) => {
    setEditing(m)
    setEditForm({ type: m.type, domain: m.domain, display_name: m.display_name, description: m.description })
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <button onClick={() => navigate('/')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0 }}>
          ← Projects
        </button>
        <h2 style={{ margin: 0, flex: 1 }}>Model Catalog</h2>
        <button
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
          style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', cursor: 'pointer' }}
        >
          {sync.isPending ? 'Syncing…' : '↻ Sync from Ollama'}
        </button>
        <button
          onClick={() => navigate('/admin/users')}
          style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
        >
          Users
        </button>
      </div>

      {sync.isError && (
        <p style={{ color: '#c00', fontSize: 13, marginBottom: 12 }}>
          Sync failed: {String(sync.error)}
        </p>
      )}

      {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}

      {models && models.length === 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
          No models yet. Click "Sync from Ollama" to discover installed models.
        </p>
      )}

      {models && models.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          {/* Header */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px 60px 90px 90px 70px 60px 60px', gap: 8, padding: '8px 14px', fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: '1px solid var(--border)', background: 'var(--surface, rgba(128,128,128,0.04))' }}>
            <span>Model</span>
            <span>Type</span>
            <span>Domain</span>
            <span>Params</span>
            <span>Context</span>
            <span>Quant</span>
            <span>Enabled</span>
            <span></span>
          </div>
          {models.map((m, i) => (
            <div
              key={m.id}
              style={{
                display: 'grid', gridTemplateColumns: '1fr 70px 60px 90px 90px 70px 60px 60px', gap: 8, padding: '10px 14px', alignItems: 'center',
                borderBottom: i < models.length - 1 ? '1px solid var(--border)' : 'none',
                opacity: m.enabled ? 1 : 0.6,
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 500, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.id}>
                  {m.display_name}
                </div>
                {m.description && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {m.description}
                  </div>
                )}
              </div>
              <span><Badge label={TYPE_LABELS[m.type] ?? m.type} color={m.type === 'llm' ? '#6b7de0' : '#059669'} /></span>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{DOMAIN_LABELS[m.domain] ?? m.domain}</span>
              <span style={{ fontSize: 12 }}>{m.parameter_size ?? '—'}</span>
              <span style={{ fontSize: 12 }}>{m.context_length ? `${(m.context_length / 1000).toFixed(0)}k` : '—'}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{m.quantization ?? '—'}</span>
              <span>
                <button
                  onClick={() => update.mutate({ id: m.id, body: { enabled: !m.enabled } })}
                  style={{
                    padding: '3px 8px', fontSize: 11, borderRadius: 3, border: '1px solid var(--border)', cursor: 'pointer',
                    background: m.enabled ? 'rgba(5,150,105,0.12)' : 'none',
                    color: m.enabled ? '#059669' : 'var(--text-muted)',
                  }}
                >
                  {m.enabled ? 'On' : 'Off'}
                </button>
              </span>
              <span>
                <button
                  onClick={() => openEdit(m)}
                  style={{ padding: '3px 8px', fontSize: 11, borderRadius: 3, border: '1px solid var(--border)', background: 'none', cursor: 'pointer' }}
                >
                  Edit
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Edit panel */}
      {editing && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setEditing(null) }}
        >
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(480px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 15 }}>{editing.display_name}</h3>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 16 }}>{editing.id}</div>

            <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Display name</label>
            <input
              value={editForm.display_name ?? ''}
              onChange={e => setEditForm(f => ({ ...f, display_name: e.target.value }))}
              style={{ width: '100%', marginBottom: 12, padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box' }}
            />

            <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Type</label>
            <select
              value={editForm.type ?? 'llm'}
              onChange={e => setEditForm(f => ({ ...f, type: e.target.value as 'llm' | 'embedding' }))}
              style={{ width: '100%', marginBottom: 12, padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box' }}
            >
              <option value="llm">LLM (language model)</option>
              <option value="embedding">Embedding model</option>
            </select>

            <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Domain</label>
            <select
              value={editForm.domain ?? 'any'}
              onChange={e => setEditForm(f => ({ ...f, domain: e.target.value }))}
              style={{ width: '100%', marginBottom: 12, padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box' }}
            >
              <option value="any">Any</option>
              <option value="text">Text</option>
              <option value="image">Image</option>
            </select>

            <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Description / notes</label>
            <textarea
              value={editForm.description ?? ''}
              onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
              rows={3}
              style={{ width: '100%', marginBottom: 16, padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13, boxSizing: 'border-box', resize: 'vertical' }}
            />

            {update.isError && (
              <p style={{ color: '#c00', fontSize: 12, marginBottom: 8 }}>{String(update.error)}</p>
            )}

            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => update.mutate({ id: editing.id, body: editForm })}
                disabled={update.isPending}
                style={{ padding: '7px 16px', borderRadius: 4, border: 'none', background: '#6b7de0', color: '#fff', fontSize: 13, cursor: 'pointer' }}
              >
                {update.isPending ? 'Saving…' : 'Save'}
              </button>
              <button onClick={() => setEditing(null)} style={{ padding: '7px 14px', borderRadius: 4, fontSize: 13 }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

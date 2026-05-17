import { useState, type ReactNode } from 'react'
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
  const [showAddModel, setShowAddModel] = useState(false)
  const [addForm, setAddForm] = useState({ id: '', type: 'embedding', domain: 'text', display_name: '', description: '' })
  const [veniceKey, setVeniceKey] = useState('')
  const [showVeniceKey, setShowVeniceKey] = useState(false)
  const [openRouterKey, setOpenRouterKey] = useState('')
  const [showOpenRouterKey, setShowOpenRouterKey] = useState(false)
  const [sortBy, setSortBy] = useState('display_name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [search, setSearch] = useState('')

  const toggleSort = (col: string) => {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortDir('asc') }
  }

  if (!me.is_admin) return <div style={{ padding: 24 }}>Access denied.</div>

  const { data: models, isLoading } = useQuery({
    queryKey: ['admin-models'],
    queryFn: () => api.admin.listModels(),
  })

  const { data: veniceStatus } = useQuery({
    queryKey: ['venice-status'],
    queryFn: () => api.admin.getVeniceStatus(),
  })

  const { data: openRouterStatus } = useQuery({
    queryKey: ['openrouter-status'],
    queryFn: () => api.admin.getOpenRouterStatus(),
  })

  const sync = useMutation({
    mutationFn: () => api.admin.syncModels(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-models'] }),
  })

  const saveVeniceKey = useMutation({
    mutationFn: () => api.admin.setVeniceKey(veniceKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['venice-status'] })
      setVeniceKey('')
    },
  })

  const clearVeniceKey = useMutation({
    mutationFn: () => api.admin.deleteVeniceKey(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['venice-status'] })
    },
  })

  const syncVenice = useMutation({
    mutationFn: () => api.admin.syncVeniceModels(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-models'] })
      qc.invalidateQueries({ queryKey: ['venice-status'] })
    },
  })

  const saveOpenRouterKey = useMutation({
    mutationFn: () => api.admin.setOpenRouterKey(openRouterKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['openrouter-status'] })
      setOpenRouterKey('')
    },
  })

  const clearOpenRouterKey = useMutation({
    mutationFn: () => api.admin.deleteOpenRouterKey(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['openrouter-status'] })
    },
  })

  const syncOpenRouter = useMutation({
    mutationFn: () => api.admin.syncOpenRouterModels(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-models'] })
      qc.invalidateQueries({ queryKey: ['openrouter-status'] })
    },
  })

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<ModelCatalogEntry> }) =>
      api.admin.updateModel(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-models'] })
      setEditing(null)
    },
  })

  const addModel = useMutation({
    mutationFn: (body: typeof addForm) => api.admin.createModel(body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-models'] }); setShowAddModel(false); setAddForm({ id: '', type: 'embedding', domain: 'text', display_name: '', description: '' }) },
  })

  const openEdit = (m: ModelCatalogEntry) => {
    setEditing(m)
    setEditForm({ type: m.type, domain: m.domain, display_name: m.display_name, description: m.description })
  }

  const q = search.trim().toLowerCase()
  const filtered = (models ?? []).filter(m =>
    !q ||
    m.display_name.toLowerCase().includes(q) ||
    m.id.toLowerCase().includes(q) ||
    (m.description ?? '').toLowerCase().includes(q)
  )

  const sorted = [...filtered].sort((a, b) => {
    let av: string | number, bv: string | number
    switch (sortBy) {
      case 'display_name': av = a.display_name.toLowerCase(); bv = b.display_name.toLowerCase(); break
      case 'type': av = a.type; bv = b.type; break
      case 'domain': av = a.domain; bv = b.domain; break
      case 'parameter_size': av = a.parameter_size ?? ''; bv = b.parameter_size ?? ''; break
      case 'context_length': av = a.context_length ?? -1; bv = b.context_length ?? -1; break
      case 'input_cost': av = a.input_cost_usd_per_mtok ?? Infinity; bv = b.input_cost_usd_per_mtok ?? Infinity; break
      case 'enabled': av = a.enabled ? 0 : 1; bv = b.enabled ? 0 : 1; break
      default: return 0
    }
    if (av < bv) return sortDir === 'asc' ? -1 : 1
    if (av > bv) return sortDir === 'asc' ? 1 : -1
    return 0
  })

  const SortHeader = ({ col, title, children }: { col: string; title?: string; children: ReactNode }) => (
    <span
      onClick={() => toggleSort(col)}
      title={title}
      style={{ cursor: 'pointer', userSelect: 'none', display: 'inline-flex', alignItems: 'center', gap: 3 }}
    >
      {children}
      <span style={{ fontSize: 9, opacity: sortBy === col ? 1 : 0.3 }}>{sortBy === col ? (sortDir === 'asc' ? '▲' : '▼') : '▲'}</span>
    </span>
  )

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
          onClick={() => setShowAddModel(true)}
          style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', cursor: 'pointer' }}
        >
          + Add Model
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

      {/* Venice section */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>Venice.ai</span>
          {veniceStatus && (
            <span style={{ fontSize: 12, color: veniceStatus.configured ? '#059669' : 'var(--text-muted)' }}>
              {veniceStatus.configured
                ? `Key set · ${veniceStatus.model_count} model${veniceStatus.model_count !== 1 ? 's' : ''} synced`
                : 'No API key set'}
            </span>
          )}
          <button
            onClick={() => syncVenice.mutate()}
            disabled={syncVenice.isPending || !veniceStatus?.configured}
            style={{ padding: '5px 12px', borderRadius: 4, fontSize: 12, border: '1px solid var(--border)', cursor: 'pointer' }}
          >
            {syncVenice.isPending ? 'Syncing…' : '↻ Sync Venice models'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
          <input
            type={showVeniceKey ? 'text' : 'password'}
            value={veniceKey}
            onChange={e => setVeniceKey(e.target.value)}
            placeholder="Venice API key…"
            style={{ flex: 1, padding: '6px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13 }}
          />
          <button
            onClick={() => setShowVeniceKey(v => !v)}
            style={{ padding: '6px 10px', borderRadius: 4, fontSize: 12, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            {showVeniceKey ? 'Hide' : 'Show'}
          </button>
          <button
            onClick={() => saveVeniceKey.mutate()}
            disabled={saveVeniceKey.isPending || !veniceKey.trim()}
            style={{ padding: '6px 14px', borderRadius: 4, fontSize: 12, border: 'none', background: '#6b7de0', color: '#fff', cursor: 'pointer' }}
          >
            {saveVeniceKey.isPending ? 'Saving…' : 'Save key'}
          </button>
          {veniceStatus?.configured && (
            <button
              onClick={() => clearVeniceKey.mutate()}
              disabled={clearVeniceKey.isPending}
              style={{ padding: '6px 14px', borderRadius: 4, fontSize: 12, border: '1px solid rgba(192,0,0,0.3)', background: 'none', color: '#c00', cursor: 'pointer' }}
            >
              {clearVeniceKey.isPending ? 'Clearing…' : 'Clear key'}
            </button>
          )}
        </div>
        {(syncVenice.isError || saveVeniceKey.isError || clearVeniceKey.isError) && (
          <p style={{ color: '#c00', fontSize: 12, margin: '8px 0 0' }}>
            {String(syncVenice.error || saveVeniceKey.error || clearVeniceKey.error)}
          </p>
        )}
      </div>

      {/* OpenRouter section */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>OpenRouter</span>
          {openRouterStatus && (
            <span style={{ fontSize: 12, color: openRouterStatus.configured ? '#059669' : 'var(--text-muted)' }}>
              {openRouterStatus.configured
                ? `Key set · ${openRouterStatus.model_count} model${openRouterStatus.model_count !== 1 ? 's' : ''} synced`
                : 'No API key set'}
            </span>
          )}
          <button
            onClick={() => syncOpenRouter.mutate()}
            disabled={syncOpenRouter.isPending || !openRouterStatus?.configured}
            style={{ padding: '5px 12px', borderRadius: 4, fontSize: 12, border: '1px solid var(--border)', cursor: 'pointer' }}
          >
            {syncOpenRouter.isPending ? 'Syncing…' : '↻ Sync OpenRouter models'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
          <input
            type={showOpenRouterKey ? 'text' : 'password'}
            value={openRouterKey}
            onChange={e => setOpenRouterKey(e.target.value)}
            placeholder="OpenRouter API key (sk-or-…)"
            style={{ flex: 1, padding: '6px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13 }}
          />
          <button
            onClick={() => setShowOpenRouterKey(v => !v)}
            style={{ padding: '6px 10px', borderRadius: 4, fontSize: 12, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            {showOpenRouterKey ? 'Hide' : 'Show'}
          </button>
          <button
            onClick={() => saveOpenRouterKey.mutate()}
            disabled={saveOpenRouterKey.isPending || !openRouterKey.trim()}
            style={{ padding: '6px 14px', borderRadius: 4, fontSize: 12, border: 'none', background: '#0ea5e9', color: '#fff', cursor: 'pointer' }}
          >
            {saveOpenRouterKey.isPending ? 'Saving…' : 'Save key'}
          </button>
          {openRouterStatus?.configured && (
            <button
              onClick={() => clearOpenRouterKey.mutate()}
              disabled={clearOpenRouterKey.isPending}
              style={{ padding: '6px 14px', borderRadius: 4, fontSize: 12, border: '1px solid rgba(192,0,0,0.3)', background: 'none', color: '#c00', cursor: 'pointer' }}
            >
              {clearOpenRouterKey.isPending ? 'Clearing…' : 'Clear key'}
            </button>
          )}
        </div>
        {(syncOpenRouter.isError || saveOpenRouterKey.isError || clearOpenRouterKey.isError) && (
          <p style={{ color: '#c00', fontSize: 12, margin: '8px 0 0' }}>
            {String(syncOpenRouter.error || saveOpenRouterKey.error || clearOpenRouterKey.error)}
          </p>
        )}
      </div>

      {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}

      {models && models.length > 0 && (
        <input
          type="search"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search models…"
          style={{
            width: '100%', boxSizing: 'border-box', padding: '7px 11px', marginBottom: 12,
            borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)',
            color: 'var(--text)', fontSize: 13,
          }}
        />
      )}

      {models && models.length === 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
          No models yet. Click "Sync from Ollama" to discover installed models.
        </p>
      )}

      {models && models.length > 0 && sorted.length === 0 && (
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>No models match "{search}".</p>
      )}

      {models && models.length > 0 && sorted.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
          {/* Header */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px 60px 90px 90px 70px 100px 60px 80px 60px', gap: 8, padding: '8px 14px', fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: '1px solid var(--border)', background: 'var(--surface, rgba(128,128,128,0.04))', minWidth: 800 }}>
            <SortHeader col="display_name">Model</SortHeader>
            <SortHeader col="type">Type</SortHeader>
            <SortHeader col="domain">Domain</SortHeader>
            <SortHeader col="parameter_size">Params</SortHeader>
            <SortHeader col="context_length">Context</SortHeader>
            <span>Quant</span>
            <SortHeader col="input_cost" title="Input / output USD per million tokens">Cost/Mtok</SortHeader>
            <SortHeader col="enabled">Enabled</SortHeader>
            <span>Default</span>
            <span></span>
          </div>
          {sorted.map((m, i) => (
            <div
              key={m.id}
              style={{
                borderBottom: i < sorted.length - 1 ? '1px solid var(--border)' : 'none',
                opacity: m.enabled ? 1 : 0.6,
                minWidth: 800,
              }}
            >
              {/* Data row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px 60px 90px 90px 70px 100px 60px 80px 60px', gap: 8, padding: '10px 14px 4px', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 500, fontSize: 13, wordBreak: 'break-word' }}>{m.display_name}</span>
                  {m.source === 'venice' && (
                    <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: '#7c3aed22', color: '#7c3aed', fontWeight: 600, letterSpacing: 0.3, flexShrink: 0 }}>
                      Venice
                    </span>
                  )}
                </div>
                <span><Badge label={TYPE_LABELS[m.type] ?? m.type} color={m.type === 'llm' ? '#6b7de0' : '#059669'} /></span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{DOMAIN_LABELS[m.domain] ?? m.domain}</span>
                <span style={{ fontSize: 12 }}>{m.parameter_size ?? '—'}</span>
                <span style={{ fontSize: 12 }}>{m.context_length ? `${(m.context_length / 1000).toFixed(0)}k` : '—'}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{m.quantization ?? '—'}</span>
                <span style={{ fontSize: 11 }}>
                  {m.input_cost_usd_per_mtok != null || m.output_cost_usd_per_mtok != null ? (
                    <span title={`Input: $${m.input_cost_usd_per_mtok ?? '?'} / Output: $${m.output_cost_usd_per_mtok ?? '?'} per million tokens`}>
                      <span style={{ color: 'var(--text)' }}>${m.input_cost_usd_per_mtok?.toFixed(2) ?? '?'}</span>
                      <span style={{ color: 'var(--text-muted)' }}> / ${m.output_cost_usd_per_mtok?.toFixed(2) ?? '?'}</span>
                    </span>
                  ) : '—'}
                </span>
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
                  {m.type === 'llm' && (
                    m.is_default
                      ? <span style={{ fontSize: 11, color: '#c08020', fontWeight: 600 }}>★ Default</span>
                      : m.enabled
                        ? <button
                            onClick={() => update.mutate({ id: m.id, body: { is_default: true } })}
                            style={{ padding: '3px 8px', fontSize: 11, borderRadius: 3, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
                          >
                            Set
                          </button>
                        : null
                  )}
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
              {/* Full-width detail row */}
              {(m.id !== m.display_name || m.description || m.privacy) && (
                <div style={{ padding: '0 14px 8px', display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {m.id !== m.display_name && (
                      <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace', wordBreak: 'break-all' }}>{m.id}</span>
                    )}
                    {m.privacy && (
                      <span
                        title={m.privacy === 'private' ? 'Prompts are never logged by Venice' : 'Prompts may be retained in anonymized form'}
                        style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 3, fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
                          background: m.privacy === 'private' ? 'rgba(5,150,105,0.12)' : 'rgba(180,83,9,0.12)',
                          color: m.privacy === 'private' ? '#059669' : '#b45309',
                        }}
                      >
                        {m.privacy === 'private' ? '🔒 Private' : '〜 Anonymized'}
                      </span>
                    )}
                  </div>
                  {m.description && (
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{m.description}</span>
                  )}
                </div>
              )}
            </div>
          ))}
          </div>
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

      {/* Add model modal */}
      {showAddModel && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setShowAddModel(false) }}>
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(420px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Add Model</h3>
            {[
              { label: 'Model ID (e.g. all-MiniLM-L6-v2)', key: 'id', type: 'text' as const },
              { label: 'Display Name', key: 'display_name', type: 'text' as const },
              { label: 'Description', key: 'description', type: 'text' as const },
            ].map(f => (
              <div key={f.key} style={{ marginBottom: 10 }}>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 3 }}>{f.label}</label>
                <input type={f.type} value={(addForm as any)[f.key]} onChange={e => setAddForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width: '100%', padding: '7px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }} />
              </div>
            ))}
            <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 3 }}>Type</label>
                <select value={addForm.type} onChange={e => setAddForm(p => ({ ...p, type: e.target.value }))}
                  style={{ width: '100%', padding: '7px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14 }}>
                  <option value="embedding">Embedding</option>
                  <option value="llm">LLM</option>
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 3 }}>Domain</label>
                <select value={addForm.domain} onChange={e => setAddForm(p => ({ ...p, domain: e.target.value }))}
                  style={{ width: '100%', padding: '7px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14 }}>
                  <option value="text">Text</option>
                  <option value="image">Image</option>
                  <option value="any">Any</option>
                </select>
              </div>
            </div>
            {addModel.isError && <p style={{ color: '#c00', fontSize: 12, marginBottom: 8 }}>{(addModel.error as Error).message}</p>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => addModel.mutate(addForm)} disabled={addModel.isPending || !addForm.id || !addForm.display_name}
                style={{ padding: '7px 16px', borderRadius: 4, border: 'none', background: '#6b7de0', color: '#fff', fontSize: 13, cursor: 'pointer' }}>
                {addModel.isPending ? 'Adding…' : 'Add'}
              </button>
              <button onClick={() => setShowAddModel(false)} style={{ padding: '7px 14px', borderRadius: 4, fontSize: 13 }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

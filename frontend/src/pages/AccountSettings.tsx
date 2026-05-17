import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

function PersonalKeySection({
  title, description, placeholder, accentColor,
  keyStatus, statusLoading,
  onSave, onClear, onSync, syncPending,
}: {
  title: string
  description: string
  placeholder: string
  accentColor: string
  keyStatus: { configured: boolean } | undefined
  statusLoading: boolean
  onSave: (key: string) => Promise<void>
  onClear: () => Promise<void>
  onSync: () => void
  syncPending: boolean
}) {
  const [apiKey, setApiKey] = useState('')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [clearState, setClearState] = useState<'idle' | 'clearing' | 'cleared' | 'error'>('idle')

  const configured = keyStatus?.configured ?? false

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!apiKey.trim()) return
    setSaveState('saving')
    setSaveError(null)
    try {
      await onSave(apiKey.trim())
      setApiKey('')
      setSaveState('saved')
      onSync()
      setTimeout(() => setSaveState('idle'), 3000)
    } catch (err: any) {
      setSaveError(err.message ?? 'Failed to save key')
      setSaveState('error')
    }
  }

  const handleClear = async () => {
    setClearState('clearing')
    try {
      await onClear()
      setClearState('cleared')
      setTimeout(() => setClearState('idle'), 3000)
    } catch {
      setClearState('error')
    }
  }

  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 20, marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>{title}</h2>
        {!statusLoading && (
          <span style={{
            fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 10,
            background: configured ? 'rgba(46,125,50,0.12)' : 'rgba(0,0,0,0.06)',
            color: configured ? '#2e7d32' : 'var(--text-muted)',
            border: `1px solid ${configured ? 'rgba(46,125,50,0.3)' : 'var(--border)'}`,
          }}>
            {configured ? 'Key configured' : 'No key'}
          </span>
        )}
      </div>

      <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 16px', lineHeight: 1.5 }}>
        {description}
      </p>

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div>
          <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>
            {configured ? 'Replace key' : 'API key'}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder={placeholder}
            autoComplete="off"
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 4,
              border: '1px solid var(--border)', background: 'var(--bg)',
              color: 'var(--text)', fontSize: 14, boxSizing: 'border-box',
            }}
          />
        </div>

        {saveState === 'error' && saveError && (
          <p style={{ fontSize: 12, color: '#c00', margin: 0 }}>{saveError}</p>
        )}

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            type="submit"
            disabled={!apiKey.trim() || saveState === 'saving' || syncPending}
            style={{
              padding: '8px 18px', background: accentColor, color: '#fff', border: 'none',
              borderRadius: 4, fontSize: 14, cursor: !apiKey.trim() || saveState === 'saving' || syncPending ? 'default' : 'pointer',
              opacity: !apiKey.trim() ? 0.6 : 1,
            }}
          >
            {saveState === 'saving' ? 'Saving…' : syncPending ? 'Syncing…' : saveState === 'saved' ? 'Saved ✓' : 'Save & sync'}
          </button>

          {configured && (
            <button
              type="button"
              onClick={handleClear}
              disabled={clearState === 'clearing'}
              style={{
                padding: '8px 18px', background: 'none', color: '#c00',
                border: '1px solid rgba(192,0,0,0.3)', borderRadius: 4, fontSize: 14,
                cursor: clearState === 'clearing' ? 'default' : 'pointer',
              }}
            >
              {clearState === 'clearing' ? 'Clearing…' : clearState === 'cleared' ? 'Cleared ✓' : 'Remove key'}
            </button>
          )}
        </div>
      </form>

      {configured && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>Sync catalog</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Fetch the full model list using your personal key so it appears in the model picker.
              </div>
            </div>
            <button
              onClick={onSync}
              disabled={syncPending}
              style={{
                padding: '7px 14px', borderRadius: 4, fontSize: 13,
                border: '1px solid var(--border)', background: 'none',
                color: 'var(--text)', cursor: syncPending ? 'default' : 'pointer',
                flexShrink: 0,
              }}
            >
              {syncPending ? 'Syncing…' : '↻ Sync catalog'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

export default function AccountSettings() {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: veniceStatus, isLoading: veniceStatusLoading } = useQuery({
    queryKey: ['venice-key-status'],
    queryFn: api.auth.veniceKeyStatus,
  })

  const { data: openRouterStatus, isLoading: openRouterStatusLoading } = useQuery({
    queryKey: ['openrouter-key-status'],
    queryFn: api.auth.openRouterKeyStatus,
  })

  const syncVenice = useMutation({
    mutationFn: () => api.auth.syncVeniceModels(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['models'] }),
  })

  const syncOpenRouter = useMutation({
    mutationFn: () => api.auth.syncOpenRouterModels(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['models'] }),
  })

  return (
    <div style={{ maxWidth: 560, margin: '0 auto', padding: 'clamp(16px, 4vw, 32px)' }}>
      <button
        onClick={() => navigate('/')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0, marginBottom: 20, fontSize: 14 }}
      >
        ← Back
      </button>

      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}>Account Settings</h1>

      <PersonalKeySection
        title="Venice AI — Personal API Key"
        description="Add your personal Venice API key to access the full Venice model catalog — independently of which models an administrator has enabled for shared use. Costs are charged directly to your Venice account."
        placeholder="sk-..."
        accentColor="#6b7de0"
        keyStatus={veniceStatus}
        statusLoading={veniceStatusLoading}
        onSave={async (key) => {
          await api.auth.setVeniceKey(key)
          qc.invalidateQueries({ queryKey: ['venice-key-status'] })
          qc.invalidateQueries({ queryKey: ['models'] })
        }}
        onClear={async () => {
          await api.auth.deleteVeniceKey()
          qc.invalidateQueries({ queryKey: ['venice-key-status'] })
          qc.invalidateQueries({ queryKey: ['models'] })
        }}
        onSync={() => syncVenice.mutate()}
        syncPending={syncVenice.isPending}
      />

      <PersonalKeySection
        title="OpenRouter — Personal API Key"
        description="Add your personal OpenRouter API key to access the full OpenRouter model catalog (GPT-4o, Claude, Gemini, and more) — independently of which models an administrator has enabled. Costs are charged directly to your OpenRouter account."
        placeholder="sk-or-..."
        accentColor="#0ea5e9"
        keyStatus={openRouterStatus}
        statusLoading={openRouterStatusLoading}
        onSave={async (key) => {
          await api.auth.setOpenRouterKey(key)
          qc.invalidateQueries({ queryKey: ['openrouter-key-status'] })
          qc.invalidateQueries({ queryKey: ['models'] })
        }}
        onClear={async () => {
          await api.auth.deleteOpenRouterKey()
          qc.invalidateQueries({ queryKey: ['openrouter-key-status'] })
          qc.invalidateQueries({ queryKey: ['models'] })
        }}
        onSync={() => syncOpenRouter.mutate()}
        syncPending={syncOpenRouter.isPending}
      />
    </div>
  )
}

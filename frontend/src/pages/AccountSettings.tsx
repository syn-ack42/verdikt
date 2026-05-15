import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export default function AccountSettings() {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: keyStatus, isLoading: statusLoading } = useQuery({
    queryKey: ['venice-key-status'],
    queryFn: api.auth.veniceKeyStatus,
  })

  const [apiKey, setApiKey] = useState('')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [clearState, setClearState] = useState<'idle' | 'clearing' | 'cleared' | 'error'>('idle')

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!apiKey.trim()) return
    setSaveState('saving')
    setSaveError(null)
    try {
      await api.auth.setVeniceKey(apiKey.trim())
      setApiKey('')
      setSaveState('saved')
      qc.invalidateQueries({ queryKey: ['venice-key-status'] })
      // Invalidate model queries so pickers reload with personal models
      qc.invalidateQueries({ queryKey: ['models'] })
      setTimeout(() => setSaveState('idle'), 3000)
    } catch (err: any) {
      setSaveError(err.message ?? 'Failed to save key')
      setSaveState('error')
    }
  }

  const handleClear = async () => {
    setClearState('clearing')
    try {
      await api.auth.deleteVeniceKey()
      setClearState('cleared')
      qc.invalidateQueries({ queryKey: ['venice-key-status'] })
      qc.invalidateQueries({ queryKey: ['models'] })
      setTimeout(() => setClearState('idle'), 3000)
    } catch {
      setClearState('error')
    }
  }

  const configured = keyStatus?.configured ?? false

  return (
    <div style={{ maxWidth: 560, margin: '0 auto', padding: 'clamp(16px, 4vw, 32px)' }}>
      <button
        onClick={() => navigate('/')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0, marginBottom: 20, fontSize: 14 }}
      >
        ← Back
      </button>

      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 24 }}>Account Settings</h1>

      <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 20, marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Venice AI — Personal API Key</h2>
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
          Add your personal Venice API key to access the full Venice model catalog — independently of
          which models an administrator has enabled for shared use. Costs are charged directly to your Venice account.
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
              placeholder="sk-..."
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
              disabled={!apiKey.trim() || saveState === 'saving'}
              style={{
                padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none',
                borderRadius: 4, fontSize: 14, cursor: !apiKey.trim() || saveState === 'saving' ? 'default' : 'pointer',
                opacity: !apiKey.trim() ? 0.6 : 1,
              }}
            >
              {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved ✓' : 'Save key'}
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
      </section>
    </div>
  )
}

import { useState } from 'react'
import { api } from '../api/client'
import type { PluginAction, WritebackResult } from '../api/types'

interface Props {
  projectId: string
  pluginName: string
  action: PluginAction
  onClose: () => void
}

function buildDefaults(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema as any).properties ?? {}
  const result: Record<string, unknown> = {}
  for (const [key, prop] of Object.entries(props as Record<string, any>)) {
    if (prop.default !== undefined) result[key] = prop.default
    else if (prop.type === 'boolean') result[key] = false
    else if (prop.type === 'string') result[key] = ''
  }
  return result
}

export default function PluginActionModal({ projectId, pluginName, action, onClose }: Props) {
  const [options, setOptions] = useState<Record<string, unknown>>(() => buildDefaults(action.options_schema))
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<WritebackResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const schema = action.options_schema as any
  const props: Record<string, any> = schema.properties ?? {}

  const handleConfirm = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.plugins.runAction(pluginName, projectId, action.name, options)
      setResult(res)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12, padding: 28, width: 400, maxWidth: '90vw' }}>
        <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>{action.title}</div>
        {action.description && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20, lineHeight: 1.5 }}>
            {action.description}
          </div>
        )}

        {!result ? (
          <>
            {Object.entries(props).map(([key, prop]) => {
              if (prop.type === 'boolean') {
                return (
                  <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, cursor: 'pointer', fontSize: 14 }}>
                    <input
                      type="checkbox"
                      checked={!!options[key]}
                      onChange={e => setOptions(o => ({ ...o, [key]: e.target.checked }))}
                      style={{ width: 16, height: 16, cursor: 'pointer' }}
                    />
                    <div>
                      <div style={{ fontWeight: 600 }}>{prop.title ?? key}</div>
                      {prop.description && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{prop.description}</div>}
                    </div>
                  </label>
                )
              }
              return (
                <label key={key} style={{ display: 'block', marginBottom: 14, fontSize: 14 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{prop.title ?? key}</div>
                  {prop.description && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{prop.description}</div>}
                  <input
                    type="text"
                    value={String(options[key] ?? '')}
                    onChange={e => setOptions(o => ({ ...o, [key]: e.target.value }))}
                    style={{ width: '100%', padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 6, fontSize: 13, boxSizing: 'border-box', background: 'var(--bg)', color: 'var(--text)' }}
                  />
                </label>
              )
            })}

            {error && (
              <div style={{ marginBottom: 16, padding: '8px 12px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6, fontSize: 13, color: '#dc2626' }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button
                onClick={onClose}
                disabled={loading}
                style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={loading}
                style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: loading ? 'default' : 'pointer', fontSize: 14, opacity: loading ? 0.6 : 1 }}
              >
                {loading ? 'Running…' : 'Confirm'}
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ marginBottom: 20, fontSize: 14, lineHeight: 1.7 }}>
              <div><span style={{ fontWeight: 600 }}>{result.updated}</span> asset{result.updated !== 1 ? 's' : ''} updated</div>
              <div style={{ color: 'var(--text-muted)' }}><span style={{ fontWeight: 600 }}>{result.skipped}</span> skipped</div>
              {result.errors.length > 0 && (
                <div style={{ marginTop: 10, padding: '8px 12px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 6, fontSize: 12, color: '#dc2626' }}>
                  {result.errors.slice(0, 5).map((e, i) => <div key={i}>{e}</div>)}
                  {result.errors.length > 5 && <div>…and {result.errors.length - 5} more</div>}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={onClose}
                style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
              >
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

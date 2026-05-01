import { useState } from 'react'
import { api } from '../api/client'
import type { WritebackResult } from '../api/types'

interface Props {
  projectId: string
  pluginName: string
  pluginTitle: string
  onClose: () => void
}

export default function WritebackModal({ projectId, pluginName, pluginTitle, onClose }: Props) {
  const [writeRatings, setWriteRatings] = useState(true)
  const [writeDescriptions, setWriteDescriptions] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<WritebackResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleConfirm = async () => {
    if (!writeRatings && !writeDescriptions) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.works.writeback(projectId, pluginName, {
        write_ratings: writeRatings,
        write_descriptions: writeDescriptions,
      })
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
      <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12, padding: 28, width: 360, maxWidth: '90vw' }}>
        <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>Write back to {pluginTitle}</div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20, lineHeight: 1.5 }}>
          Verdikt will update assets in {pluginTitle} based on your ratings and AI-generated descriptions.
        </div>

        {!result ? (
          <>
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, cursor: 'pointer', fontSize: 14 }}>
              <input
                type="checkbox"
                checked={writeRatings}
                onChange={e => setWriteRatings(e.target.checked)}
                style={{ width: 16, height: 16, cursor: 'pointer' }}
              />
              <div>
                <div style={{ fontWeight: 600 }}>Write ratings as star ratings</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Weighted average dimension score → 1–5 stars</div>
              </div>
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24, cursor: 'pointer', fontSize: 14 }}>
              <input
                type="checkbox"
                checked={writeDescriptions}
                onChange={e => setWriteDescriptions(e.target.checked)}
                style={{ width: 16, height: 16, cursor: 'pointer' }}
              />
              <div>
                <div style={{ fontWeight: 600 }}>Write AI descriptions</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Appended as <code style={{ fontSize: 11 }}>#verdikt: …</code> (idempotent)</div>
              </div>
            </label>

            {error && (
              <div style={{ marginBottom: 16, padding: '8px 12px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 6, fontSize: 13, color: '#dc2626' }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                onClick={onClose}
                disabled={loading}
                style={{ padding: '8px 18px', background: 'none', border: '1px solid var(--border)', borderRadius: 6, cursor: 'pointer', fontSize: 14 }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={loading || (!writeRatings && !writeDescriptions)}
                style={{ padding: '8px 18px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 6, cursor: loading || (!writeRatings && !writeDescriptions) ? 'default' : 'pointer', fontSize: 14, opacity: loading || (!writeRatings && !writeDescriptions) ? 0.6 : 1 }}
              >
                {loading ? 'Writing…' : 'Confirm'}
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ marginBottom: 20, fontSize: 14, lineHeight: 1.7 }}>
              <div><span style={{ fontWeight: 600 }}>{result.updated}</span> asset{result.updated !== 1 ? 's' : ''} updated</div>
              <div style={{ color: 'var(--text-muted)' }}><span style={{ fontWeight: 600 }}>{result.skipped}</span> skipped (no ratings or descriptions yet)</div>
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

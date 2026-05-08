import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DimensionProposal, DiscoveryAnalysisResult } from '../api/types'

interface Props {
  projectId: string
  onClose: () => void
  onApplied: () => void
}

type IrrelevantAction = 'keep' | 'downweight' | 'remove'

export default function DiscoveryAnalysisModal({ projectId, onClose, onApplied }: Props) {
  const qc = useQueryClient()

  const [phase, setPhase] = useState<'running' | 'review' | 'applying' | 'error'>('running')
  const [progressLabel, setProgressLabel] = useState('Preparing…')
  const [progressDone, setProgressDone] = useState(0)
  const [progressTotal, setProgressTotal] = useState(1)
  const [result, setResult] = useState<DiscoveryAnalysisResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  // Editable proposal state
  const [proposals, setProposals] = useState<DimensionProposal[]>([])
  const [included, setIncluded] = useState<boolean[]>([])
  const [irrelevantActions, setIrrelevantActions] = useState<Record<string, IrrelevantAction>>({})

  const abortRef = useRef(false)

  useEffect(() => {
    abortRef.current = false
    let cancelled = false

    api.discovery.analyseStream(projectId, (event) => {
      if (cancelled) return
      if (event.type === 'progress') {
        const phaseLabel = event.phase === 'describing'
          ? `Describing chunks (${event.done} / ${event.total})…`
          : 'Synthesising dimensions…'
        setProgressLabel(phaseLabel)
        setProgressDone(event.done)
        setProgressTotal(event.total)
      } else if (event.type === 'complete') {
        setResult(event.result)
        setProposals(event.result.proposed_dimensions)
        setIncluded(event.result.proposed_dimensions.map(() => true))
        setIrrelevantActions(
          Object.fromEntries(event.result.irrelevant_existing.map(n => [n, 'keep' as IrrelevantAction]))
        )
        setPhase('review')
      } else if (event.type === 'error') {
        setErrorMsg(event.message)
        setPhase('error')
      }
    }).catch(err => {
      if (!cancelled) {
        setErrorMsg(err?.message ?? 'Analysis failed')
        setPhase('error')
      }
    })

    return () => { cancelled = true }
  }, [projectId])

  const updateProposal = (i: number, patch: Partial<DimensionProposal>) => {
    setProposals(prev => prev.map((p, idx) => idx === i ? { ...p, ...patch } : p))
  }

  const handleApply = async () => {
    if (!result) return
    setPhase('applying')

    // Build the final dimension list:
    // 1. Selected proposed dims (with edits)
    const finalDims: { name: string; description: string; weight: number }[] = []
    proposals.forEach((p, i) => {
      if (!included[i] || !p.name.trim()) return
      finalDims.push({ name: p.name.trim(), description: p.description.trim(), weight: p.weight })
    })

    // 2. Irrelevant existing dims according to user actions (keep/downweight survive, remove drops)
    // These come from the project's existing dimensions, not from proposals.
    // The apply endpoint only takes the new dimension list, so we need to fetch the project
    // to get current non-irrelevant dims and merge.
    // Simpler: the apply endpoint replaces all dims. We should pass everything we want to keep.
    // Since we only have the irrelevant names here (not the full existing dims), we fetch the project.
    let existingToKeep: { name: string; description: string; weight: number }[] = []
    try {
      const project = await api.projects.get(projectId)
      const irrelevantNames = new Set(result.irrelevant_existing)
      for (const dim of project.rating_dimensions) {
        // Skip dims that are being replaced by a matched proposal
        const matchedByProposal = proposals.some(
          (p, i) => included[i] && !p.is_new && p.existing_name === dim.name
        )
        if (matchedByProposal) continue
        // Skip truly new proposals that aren't mapped to existing dims
        if (!irrelevantNames.has(dim.name)) {
          // It's an existing dim not flagged as irrelevant — keep it
          existingToKeep.push({ name: dim.name, description: dim.description, weight: dim.weight })
        } else {
          // It's flagged irrelevant
          const action = irrelevantActions[dim.name] ?? 'keep'
          if (action === 'remove') continue
          existingToKeep.push({
            name: dim.name,
            description: dim.description,
            weight: action === 'downweight' ? Math.max(0.1, dim.weight * 0.5) : dim.weight,
          })
        }
      }
    } catch {
      // If we can't fetch the project, just use what we have
    }

    const allDims = [...existingToKeep, ...finalDims]
    if (allDims.length === 0) {
      setPhase('review')
      return
    }

    try {
      await api.discovery.apply(projectId, { dimensions: allDims })
      qc.invalidateQueries({ queryKey: ['projects', projectId] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      onApplied()
    } catch (err: unknown) {
      setErrorMsg((err as Error)?.message ?? 'Apply failed')
      setPhase('error')
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget && phase !== 'running') onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)',
        color: 'var(--text)',
        borderRadius: 10,
        width: 'min(700px, 94vw)',
        maxHeight: '90vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>
            {phase === 'running' ? 'Analysing preferences…'
              : phase === 'review' ? 'Proposed dimensions'
              : phase === 'applying' ? 'Applying…'
              : 'Analysis error'}
          </h3>
          {phase !== 'running' && (
            <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}>×</button>
          )}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>

          {/* Running */}
          {phase === 'running' && (
            <div>
              <p style={{ color: 'var(--text-muted)', margin: '0 0 12px' }}>{progressLabel}</p>
              <div style={{ background: 'var(--border)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
                <div style={{
                  background: 'var(--accent)',
                  height: '100%',
                  width: progressTotal > 0 ? `${Math.round((progressDone / progressTotal) * 100)}%` : '0%',
                  transition: 'width 0.3s',
                }} />
              </div>
            </div>
          )}

          {/* Error */}
          {phase === 'error' && (
            <p style={{ color: '#c00' }}>{errorMsg || 'An error occurred during analysis.'}</p>
          )}

          {/* Applying */}
          {phase === 'applying' && (
            <p style={{ color: 'var(--text-muted)' }}>Saving dimensions…</p>
          )}

          {/* Review */}
          {phase === 'review' && result && (
            <>
              {result.analysis_notes && (
                <p style={{ fontStyle: 'italic', color: 'var(--text-muted)', fontSize: 13, margin: '0 0 16px' }}>
                  {result.analysis_notes}
                </p>
              )}

              <h4 style={{ margin: '0 0 10px', fontSize: 14 }}>Proposed dimensions</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
                {proposals.map((p, i) => (
                  <div key={i} style={{
                    display: 'flex',
                    gap: 8,
                    alignItems: 'flex-start',
                    opacity: included[i] ? 1 : 0.45,
                    padding: '10px 12px',
                    background: 'var(--card-bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 7,
                  }}>
                    <input
                      type="checkbox"
                      checked={included[i]}
                      onChange={e => setIncluded(prev => prev.map((v, idx) => idx === i ? e.target.checked : v))}
                      style={{ marginTop: 4, flexShrink: 0 }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
                        <input
                          value={p.name}
                          onChange={e => updateProposal(i, { name: e.target.value })}
                          disabled={!included[i]}
                          placeholder="Dimension name"
                          style={{ fontWeight: 600, fontSize: 14, width: 160, flexShrink: 0 }}
                        />
                        {p.is_new
                          ? <span style={{ fontSize: 11, padding: '2px 6px', background: '#e8f5e9', color: '#2e7d32', borderRadius: 4 }}>New</span>
                          : <span style={{ fontSize: 11, padding: '2px 6px', background: '#e3f2fd', color: '#1565c0', borderRadius: 4 }}>Matches: {p.existing_name}</span>
                        }
                      </div>
                      <input
                        value={p.description}
                        onChange={e => updateProposal(i, { description: e.target.value })}
                        disabled={!included[i]}
                        placeholder="Description (what does a high score mean?)"
                        style={{ width: '100%', fontSize: 13, boxSizing: 'border-box', marginBottom: 6 }}
                      />
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                        <label>Importance:</label>
                        <input
                          type="number"
                          min={0.1} max={2.0} step={0.1}
                          value={p.weight}
                          onChange={e => updateProposal(i, { weight: parseFloat(e.target.value) || 1.0 })}
                          disabled={!included[i]}
                          style={{ width: 60, fontSize: 13 }}
                        />
                        <span style={{ color: 'var(--text-muted)' }}>
                          {p.weight >= 1.5 ? '(high)' : p.weight <= 0.6 ? '(low)' : '(normal)'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Irrelevant existing dims */}
              {result.irrelevant_existing.length > 0 && (
                <>
                  <h4 style={{ margin: '0 0 6px', fontSize: 14 }}>Existing dimensions that didn't surface</h4>
                  <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px' }}>
                    These dimensions were never a distinctive quality in your liked or disliked samples.
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
                    {result.irrelevant_existing.map(name => (
                      <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 6 }}>
                        <span style={{ flex: 1, fontSize: 14, fontWeight: 500 }}>{name}</span>
                        {(['keep', 'downweight', 'remove'] as IrrelevantAction[]).map(action => (
                          <label key={action} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                            <input
                              type="radio"
                              name={`irrelevant-${name}`}
                              value={action}
                              checked={(irrelevantActions[name] ?? 'keep') === action}
                              onChange={() => setIrrelevantActions(prev => ({ ...prev, [name]: action }))}
                            />
                            {action === 'keep' ? 'Keep' : action === 'downweight' ? 'Downweight (×0.5)' : 'Remove'}
                          </label>
                        ))}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {phase === 'review' && (
          <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button onClick={onClose} style={{ padding: '8px 18px', borderRadius: 6, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', fontSize: 14 }}>
              Cancel
            </button>
            <button
              onClick={handleApply}
              disabled={!included.some(Boolean)}
              style={{
                padding: '8px 22px',
                borderRadius: 6,
                border: 'none',
                background: 'var(--accent)',
                color: '#fff',
                fontSize: 14,
                fontWeight: 600,
                cursor: included.some(Boolean) ? 'pointer' : 'default',
                opacity: included.some(Boolean) ? 1 : 0.5,
              }}
            >
              Apply to project
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

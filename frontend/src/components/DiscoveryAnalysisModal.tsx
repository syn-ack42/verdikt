import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { DimensionProposal, DiscoveryAnalysisResult, DiscoveryAnalysisStatus } from '../api/types'

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

interface Props {
  projectId: string
  analysisStatus: DiscoveryAnalysisStatus
  onClose: () => void
  onApplied: () => void
}

type IrrelevantAction = 'keep' | 'downweight' | 'remove'

export default function DiscoveryAnalysisModal({ projectId, analysisStatus, onClose, onApplied }: Props) {
  const qc = useQueryClient()
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState('')

  const { data: project } = useQuery({
    queryKey: ['projects', projectId],
    queryFn: () => api.projects.get(projectId),
  })

  const result: DiscoveryAnalysisResult | null = analysisStatus.result

  // Editable proposal state — initialised from result once available
  const [proposals, setProposals] = useState<DimensionProposal[]>(() => result?.proposed_dimensions ?? [])
  const [included, setIncluded] = useState<boolean[]>(() => result?.proposed_dimensions.map(() => true) ?? [])
  const [irrelevantActions, setIrrelevantActions] = useState<Record<string, IrrelevantAction>>(
    () => Object.fromEntries((result?.irrelevant_existing ?? []).map(n => [n, 'keep' as IrrelevantAction]))
  )

  // When the modal mounts while analysis is still running (result=null), sync state
  // once the result arrives. Using a ref+effect avoids calling setState during render.
  const needsResultInit = useRef(result === null)
  useEffect(() => {
    if (result !== null && needsResultInit.current) {
      needsResultInit.current = false
      setProposals(result.proposed_dimensions)
      setIncluded(result.proposed_dimensions.map(() => true))
      setIrrelevantActions(Object.fromEntries(result.irrelevant_existing.map(n => [n, 'keep' as IrrelevantAction])))
    }
  }, [result])

  const updateProposal = (i: number, patch: Partial<DimensionProposal>) => {
    setProposals(prev => prev.map((p, idx) => idx === i ? { ...p, ...patch } : p))
  }

  const handleApply = async () => {
    if (!result) return
    setApplying(true)
    setApplyError('')

    // Collect renames: matched proposals where the user changed the name
    const dimension_renames: Record<string, string> = {}
    proposals.forEach((p, i) => {
      if (included[i] && !p.is_new && p.existing_name && p.name.trim() !== p.existing_name) {
        dimension_renames[p.existing_name] = p.name.trim()
      }
    })

    const finalDims: { name: string; description: string; weight: number }[] = []
    proposals.forEach((p, i) => {
      if (!included[i] || !p.name.trim()) return
      finalDims.push({ name: p.name.trim(), description: p.description.trim(), weight: p.weight })
    })

    const existingToKeep: { name: string; description: string; weight: number }[] = []
    const currentDims = project?.rating_dimensions ?? []
    const irrelevantNames = new Set(result.irrelevant_existing)
    for (const dim of currentDims) {
      const matchedByProposal = proposals.some(
        (p, i) => included[i] && !p.is_new && p.existing_name === dim.name
      )
      if (matchedByProposal) continue
      if (!irrelevantNames.has(dim.name)) {
        existingToKeep.push({ name: dim.name, description: dim.description, weight: dim.weight })
      } else {
        const action = irrelevantActions[dim.name] ?? 'keep'
        if (action === 'remove') continue
        existingToKeep.push({
          name: dim.name,
          description: dim.description,
          weight: action === 'downweight' ? Math.max(0.1, dim.weight * 0.5) : dim.weight,
        })
      }
    }

    const allDims = [...existingToKeep, ...finalDims]
    if (allDims.length === 0) {
      setApplyError('Select at least one dimension to apply.')
      setApplying(false)
      return
    }

    try {
      await api.discovery.apply(projectId, {
        dimensions: allDims,
        ...(Object.keys(dimension_renames).length > 0 ? { dimension_renames } : {}),
      })
      await api.discovery.clearAnalysisResult(projectId)
      qc.invalidateQueries({ queryKey: ['projects', projectId] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['discovery-status', projectId] })
      onApplied()
    } catch (err: unknown) {
      setApplyError((err as Error)?.message ?? 'Apply failed')
      setApplying(false)
    }
  }

  const running = analysisStatus.running
  const phaseDone = analysisStatus.done
  const phaseTotal = analysisStatus.total
  const tokens = analysisStatus.tokens_prompt + analysisStatus.tokens_completion

  const progressPct = phaseTotal > 0 ? Math.round((phaseDone / phaseTotal) * 100) : 0
  const phaseLabel = analysisStatus.phase === 'describing'
    ? `Describing chunks (${phaseDone} / ${phaseTotal})…`
    : analysisStatus.phase === 'synthesising'
    ? 'Synthesising dimensions…'
    : running ? 'Preparing…' : ''

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
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
          <div>
            <h3 style={{ margin: 0, fontSize: 16 }}>
              {running ? 'Analysing preferences…' : result ? 'Proposed dimensions' : 'Analysis'}
            </h3>
            {tokens > 0 && (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{fmtTokens(tokens)} tokens</span>
            )}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>

          {/* Running progress */}
          {running && (
            <div style={{ marginBottom: 20 }}>
              <p style={{ color: 'var(--text-muted)', margin: '0 0 8px', fontSize: 14 }}>{phaseLabel}</p>
              <div style={{ background: 'var(--border)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
                <div style={{
                  background: '#6b7de0',
                  height: '100%',
                  width: `${progressPct}%`,
                  transition: 'width 0.5s',
                }} />
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
                Running in the background — you can close this and come back later.
              </p>
            </div>
          )}

          {/* Error */}
          {analysisStatus.error && !running && (
            <div>
              <p style={{ color: '#c00', margin: '0 0 8px' }}>{analysisStatus.error}</p>
              {analysisStatus.can_resume && (
                <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: 0 }}>
                  Chunk descriptions were saved — you can retry just the synthesis step without re-running all LLM calls.
                </p>
              )}
            </div>
          )}

          {/* Applying */}
          {applying && <p style={{ color: 'var(--text-muted)' }}>Saving dimensions…</p>}

          {/* Review */}
          {!applying && result && (() => {
            const proposedExistingNames = new Set(
              result.proposed_dimensions.filter(p => !p.is_new).map(p => p.existing_name ?? '')
            )
            const irrelevantSet = new Set(result.irrelevant_existing)
            const confirmedDims = (project?.rating_dimensions ?? []).filter(
              d => !proposedExistingNames.has(d.name) && !irrelevantSet.has(d.name)
            )
            return (
            <>
              {result.analysis_notes && (
                <p style={{ fontStyle: 'italic', color: 'var(--text-muted)', fontSize: 13, margin: '0 0 16px' }}>
                  {result.analysis_notes}
                </p>
              )}

              {confirmedDims.length > 0 && (
                <>
                  <h4 style={{ margin: '0 0 6px', fontSize: 14 }}>Confirmed — surfaced as expected</h4>
                  <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px' }}>
                    These dimensions appeared clearly in your reactions and will be kept unchanged.
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 24 }}>
                    {confirmedDims.map(d => (
                      <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', background: 'var(--card-bg)', border: '1px solid var(--border)', borderRadius: 6 }}>
                        <span style={{ fontSize: 11, padding: '2px 6px', background: 'rgba(107,125,224,0.12)', color: '#6b7de0', borderRadius: 4, fontWeight: 600, flexShrink: 0 }}>✓</span>
                        <span style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{d.name}</span>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{d.description}</span>
                      </div>
                    ))}
                  </div>
                </>
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
                        placeholder="Description"
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
                        <span>{p.weight >= 1.5 ? '(high)' : p.weight <= 0.6 ? '(low)' : '(normal)'}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {result.irrelevant_existing.length > 0 && (
                <>
                  <h4 style={{ margin: '0 0 6px', fontSize: 14 }}>Existing dimensions that didn't surface</h4>
                  <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px' }}>
                    These never appeared as a distinctive quality in your reactions.
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

              {applyError && <p style={{ color: '#c00', marginTop: 8, fontSize: 13 }}>{applyError}</p>}
            </>
            )
          })()}
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          {running && (
            <button
              onClick={async () => { await api.discovery.cancelAnalysis(projectId); qc.invalidateQueries({ queryKey: ['discovery-status', projectId] }); onClose() }}
              style={{ padding: '8px 18px', borderRadius: 6, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', fontSize: 14, color: '#c00' }}
            >
              Cancel analysis
            </button>
          )}
          {!running && (analysisStatus.error || (result && result.proposed_dimensions.length === 0 && (result.irrelevant_existing?.length ?? 0) === 0)) && (<>
            {analysisStatus.can_resume && (
              <button
                onClick={async () => {
                  await api.discovery.resumeAnalysis(projectId)
                  qc.invalidateQueries({ queryKey: ['discovery-status', projectId] })
                }}
                style={{ padding: '8px 18px', borderRadius: 6, border: 'none', background: '#6b7de0', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 600 }}
              >
                Retry synthesis
              </button>
            )}
            <button
              onClick={async () => {
                await api.discovery.clearAnalysisResult(projectId)
                await api.discovery.startAnalysis(projectId)
                qc.invalidateQueries({ queryKey: ['discovery-status', projectId] })
              }}
              style={{ padding: '8px 18px', borderRadius: 6, border: analysisStatus.can_resume ? '1px solid var(--border)' : 'none', background: analysisStatus.can_resume ? 'none' : '#6b7de0', color: analysisStatus.can_resume ? 'var(--text-muted)' : '#fff', cursor: 'pointer', fontSize: 14, fontWeight: analysisStatus.can_resume ? 400 : 600 }}
            >
              {analysisStatus.can_resume ? 'Start over' : 'Retry analysis'}
            </button>
          </>)}
          <button onClick={onClose} style={{ padding: '8px 18px', borderRadius: 6, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', fontSize: 14 }}>
            {running ? 'Continue in background' : 'Close'}
          </button>
          {result && result.proposed_dimensions.length > 0 && !applying && (
            <button
              onClick={handleApply}
              disabled={!included.some(Boolean)}
              style={{
                padding: '8px 22px',
                borderRadius: 6,
                border: 'none',
                background: '#6b7de0',
                color: '#fff',
                fontSize: 14,
                fontWeight: 600,
                cursor: included.some(Boolean) ? 'pointer' : 'default',
                opacity: included.some(Boolean) ? 1 : 0.5,
              }}
            >
              Apply to project
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

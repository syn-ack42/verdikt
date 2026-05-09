import type { RatingDimension } from '../api/types'

interface Props {
  dimensions: RatingDimension[]
  onChange: (dims: RatingDimension[]) => void
  /** Original dimension names at the point the editor was opened — used to detect edits. */
  originalNames?: string[]
  /** Original dimension descriptions at the point the editor was opened. */
  originalDescriptions?: string[]
  /** Set of dimension names that already have rating data. */
  ratedNames?: Set<string>
}

const WARNING = 'Existing ratings were given under the previous meaning — a significant change here may make them misleading.'

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '7px 10px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg)',
  color: 'var(--text)',
  fontSize: 14,
  boxSizing: 'border-box',
}

export default function DimensionEditor({
  dimensions, onChange, originalNames, originalDescriptions, ratedNames,
}: Props) {
  const update = (i: number, patch: Partial<RatingDimension>) => {
    const next = dimensions.map((d, idx) => idx === i ? { ...d, ...patch } : d)
    onChange(next)
  }

  const add = () => onChange([...dimensions, { name: '', description: '', weight: 1.0 }])

  const remove = (i: number) => {
    const originalName = originalNames?.[i]
    const wasRated = originalName !== undefined && ratedNames?.has(originalName)
    if (wasRated && !confirm(`Ratings for "${originalName}" will be permanently lost. Remove anyway?`)) return
    onChange(dimensions.filter((_, idx) => idx !== i))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {dimensions.map((dim, i) => {
        const originalName = originalNames?.[i]
        const originalDesc = originalDescriptions?.[i]
        const wasRated = originalName !== undefined && ratedNames?.has(originalName)
        const nameChanged = wasRated && originalName !== undefined && dim.name !== originalName
        const descChanged = wasRated && originalDesc !== undefined && dim.description !== originalDesc

        return (
          <div key={i} style={{
            padding: '10px 12px',
            background: 'var(--card-bg)',
            border: '1px solid var(--border)',
            borderRadius: 7,
          }}>
            {/* Row 1: name + weight + remove */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'flex-start' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <input
                  placeholder="Dimension name"
                  value={dim.name}
                  onChange={e => update(i, { name: e.target.value })}
                  style={{ ...inputStyle, borderColor: nameChanged ? '#f59e0b' : undefined, fontWeight: 500 }}
                />
                {nameChanged && (
                  <p style={{ margin: '3px 0 0', fontSize: 11, color: '#b45309', lineHeight: 1.3 }}>{WARNING}</p>
                )}
              </div>
              <div style={{ flexShrink: 0 }}>
                <input
                  type="number"
                  min={0.1} max={5.0} step={0.1}
                  title="Importance weight (1.0 = normal)"
                  value={dim.weight ?? 1.0}
                  onChange={e => update(i, { weight: parseFloat(e.target.value) || 1.0 })}
                  style={{
                    ...inputStyle,
                    width: 64,
                    color: (dim.weight ?? 1.0) !== 1.0 ? '#6b7de0' : undefined,
                    fontWeight: (dim.weight ?? 1.0) !== 1.0 ? 600 : undefined,
                  }}
                />
              </div>
              <button
                type="button"
                onClick={() => remove(i)}
                aria-label="Remove dimension"
                style={{
                  flexShrink: 0,
                  padding: '0 8px',
                  height: 34,
                  background: 'none',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  cursor: 'pointer',
                  fontSize: 16,
                  color: 'var(--text-muted)',
                  lineHeight: 1,
                }}
              >
                ×
              </button>
            </div>
            {/* Row 2: description */}
            <div>
              <input
                placeholder="Description — what a high score means"
                value={dim.description}
                onChange={e => update(i, { description: e.target.value })}
                style={{ ...inputStyle, borderColor: descChanged ? '#f59e0b' : undefined }}
              />
              {descChanged && (
                <p style={{ margin: '3px 0 0', fontSize: 11, color: '#b45309', lineHeight: 1.3 }}>{WARNING}</p>
              )}
            </div>
          </div>
        )
      })}
      <button
        type="button"
        onClick={add}
        style={{
          padding: '8px 14px',
          background: 'none',
          border: '1px dashed var(--border)',
          borderRadius: 6,
          cursor: 'pointer',
          fontSize: 13,
          color: 'var(--text-muted)',
          textAlign: 'left',
        }}
      >
        + Add dimension
      </button>
    </div>
  )
}

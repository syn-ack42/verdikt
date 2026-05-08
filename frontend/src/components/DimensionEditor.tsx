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

const warnStyle: React.CSSProperties = {
  margin: '2px 0 0',
  fontSize: 11,
  color: '#b45309',
  lineHeight: 1.3,
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
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <div style={{ width: 160, flexShrink: 0 }}>
              <input
                placeholder="Name"
                value={dim.name}
                onChange={e => update(i, { name: e.target.value })}
                style={{ width: '100%', borderColor: nameChanged ? '#f59e0b' : undefined, boxSizing: 'border-box' }}
              />
              {nameChanged && <p style={warnStyle}>{WARNING}</p>}
            </div>
            <div style={{ flex: 1 }}>
              <input
                placeholder="Description"
                value={dim.description}
                onChange={e => update(i, { description: e.target.value })}
                style={{ width: '100%', borderColor: descChanged ? '#f59e0b' : undefined, boxSizing: 'border-box' }}
              />
              {descChanged && <p style={warnStyle}>{WARNING}</p>}
            </div>
            <div style={{ width: 60, flexShrink: 0 }}>
              <input
                type="number"
                min={0.1}
                max={5.0}
                step={0.1}
                title="Importance weight (1.0 = normal)"
                value={dim.weight ?? 1.0}
                onChange={e => update(i, { weight: parseFloat(e.target.value) || 1.0 })}
                style={{ width: '100%', boxSizing: 'border-box', color: (dim.weight ?? 1.0) !== 1.0 ? 'var(--accent)' : undefined }}
              />
            </div>
            <button type="button" onClick={() => remove(i)} style={{ marginTop: 2 }} aria-label="Remove dimension">×</button>
          </div>
        )
      })}
      <button type="button" onClick={add}>+ Add dimension</button>
    </div>
  )
}

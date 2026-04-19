import type { RatingDimension } from '../api/types'

interface Props {
  dimensions: RatingDimension[]
  onChange: (dims: RatingDimension[]) => void
}

export default function DimensionEditor({ dimensions, onChange }: Props) {
  const update = (i: number, patch: Partial<RatingDimension>) => {
    const next = dimensions.map((d, idx) => idx === i ? { ...d, ...patch } : d)
    onChange(next)
  }

  const add = () => onChange([...dimensions, { name: '', description: '', weight: 1.0 }])
  const remove = (i: number) => onChange(dimensions.filter((_, idx) => idx !== i))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {dimensions.map((dim, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <input
            placeholder="Name"
            value={dim.name}
            onChange={e => update(i, { name: e.target.value })}
            style={{ width: 160 }}
          />
          <input
            placeholder="Description"
            value={dim.description}
            onChange={e => update(i, { description: e.target.value })}
            style={{ flex: 1 }}
          />
          <button type="button" onClick={() => remove(i)} aria-label="Remove dimension">×</button>
        </div>
      ))}
      <button type="button" onClick={add}>+ Add dimension</button>
    </div>
  )
}

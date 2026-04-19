interface Props {
  name: string
  score: number | undefined
  active: boolean
  onScore: (score: number) => void
  onFocus: () => void
}

export default function RatingSlider({ name, score, active, onScore, onFocus }: Props) {
  return (
    <div
      onClick={onFocus}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '6px 8px',
        borderRadius: 4,
        background: active ? 'rgba(107,125,224,0.15)' : 'transparent',
        border: active ? '1px solid #6b7de0' : '1px solid transparent',
        cursor: 'default',
      }}
    >
      <span style={{ width: 140, fontWeight: active ? 600 : 400 }}>{name}</span>
      <div style={{ display: 'flex', gap: 6 }}>
        {[1, 2, 3, 4, 5].map(v => (
          <button
            key={v}
            onClick={e => { e.stopPropagation(); onScore(v) }}
            style={{
              width: 36,
              height: 36,
              borderRadius: 4,
              border: score === v ? '1px solid #6b7de0' : '1px solid #666',
              background: score === v ? '#6b7de0' : 'transparent',
              color: score === v ? '#fff' : 'inherit',
              fontWeight: score === v ? 700 : 400,
              cursor: 'pointer',
            }}
          >
            {v}
          </button>
        ))}
      </div>
      {score !== undefined && (
        <span style={{ color: '#6b7de0', fontSize: 13 }}>✓</span>
      )}
    </div>
  )
}

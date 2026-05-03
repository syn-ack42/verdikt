import { useState } from 'react'
import { useIsMobile } from '../hooks/useIsMobile'

interface Props {
  name: string
  description?: string
  score: number | undefined
  active: boolean
  onScore: (score: number) => void
  onFocus: () => void
}

export default function RatingSlider({ name, description, score, active, onScore, onFocus }: Props) {
  const isMobile = useIsMobile()
  const [showDesc, setShowDesc] = useState(false)

  return (
    <div
      onClick={onFocus}
      style={{
        display: 'flex',
        flexDirection: 'column',
        padding: isMobile ? '6px 8px' : '3px 8px',
        borderRadius: 4,
        background: active ? 'rgba(107,125,224,0.15)' : 'transparent',
        border: active ? '1px solid #6b7de0' : '1px solid transparent',
        cursor: 'default',
      }}
    >
      <div style={{
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        alignItems: isMobile ? 'stretch' : 'center',
        gap: isMobile ? 6 : 12,
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          overflow: 'hidden',
          ...(!isMobile && { flex: '0 0 140px' }),
        }}>
          <span style={{
            fontWeight: active ? 600 : 400,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>{name}</span>
          {description && (
            <button
              onClick={e => { e.stopPropagation(); setShowDesc(v => !v) }}
              style={{
                background: 'none',
                border: 'none',
                padding: '0 2px',
                cursor: 'pointer',
                fontSize: 13,
                lineHeight: 1,
                color: showDesc ? '#6b7de0' : 'var(--text-muted)',
                flexShrink: 0,
              }}
            >
              ⓘ
            </button>
          )}
        </div>
        <div style={{ display: 'flex', gap: isMobile ? 4 : 4 }}>
          {[1, 2, 3, 4, 5].map(v => {
            const selected = score !== undefined && Math.round(score) === v
            return (
              <button
                key={v}
                onClick={e => { e.stopPropagation(); onScore(v) }}
                style={{
                  flex: isMobile ? 1 : undefined,
                  width: isMobile ? undefined : 32,
                  height: isMobile ? undefined : 32,
                  minHeight: isMobile ? 44 : undefined,
                  padding: 0,
                  borderRadius: 4,
                  border: selected ? '1px solid #6b7de0' : '1px solid var(--border)',
                  background: selected ? '#6b7de0' : 'transparent',
                  color: selected ? '#fff' : 'inherit',
                  fontWeight: selected ? 700 : 400,
                  fontSize: 13,
                  cursor: 'pointer',
                }}
              >
                {v}
              </button>
            )
          })}
        </div>
      </div>
      {showDesc && description && (
        <div style={{ marginTop: 5, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, paddingRight: 4 }}>
          {description}
        </div>
      )}
    </div>
  )
}

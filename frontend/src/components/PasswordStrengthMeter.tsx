import { useEffect, useMemo, useState } from 'react'
import { zxcvbn, zxcvbnOptions } from '@zxcvbn-ts/core'

// Language packs are loaded lazily on first render so they don't bloat the
// initial JS bundle. Until the async load finishes, scorePassword returns
// score=0 (submit stays blocked while the user is still typing anyway).
let _initialized = false
let _initPromise: Promise<void> | null = null

function _ensureInit(): Promise<void> {
  if (!_initPromise) {
    _initPromise = Promise.all([
      import('@zxcvbn-ts/language-common'),
      import('@zxcvbn-ts/language-en'),
    ]).then(([common, en]) => {
      zxcvbnOptions.setOptions({
        translations: en.translations,
        graphs: common.adjacencyGraphs,
        dictionary: {
          ...common.dictionary,
          ...en.dictionary,
        },
      })
      _initialized = true
    })
  }
  return _initPromise
}

const SCORE_LABELS = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong']
const SCORE_COLORS = ['#c00', '#e05000', '#c08020', '#2e7d32', '#1b5e20']

interface Props {
  password: string
  style?: React.CSSProperties
}

export function scorePassword(password: string): { score: number; feedback: string } {
  if (!password || !_initialized) return { score: 0, feedback: '' }
  const result = zxcvbn(password)
  const warning = result.feedback.warning || ''
  const suggestion = result.feedback.suggestions?.[0] || ''
  return { score: result.score, feedback: warning || suggestion }
}

export default function PasswordStrengthMeter({ password, style }: Props) {
  const [ready, setReady] = useState(_initialized)

  useEffect(() => {
    if (!_initialized) {
      _ensureInit().then(() => setReady(true))
    }
  }, [])

  const { score, feedback } = useMemo(() => scorePassword(password), [password, ready])

  if (!password) return null

  const color = SCORE_COLORS[score]
  const label = SCORE_LABELS[score]

  return (
    <div style={{ marginTop: 6, ...style }}>
      <div style={{ display: 'flex', gap: 3, marginBottom: 4 }}>
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} style={{
            flex: 1, height: 3, borderRadius: 2,
            background: i <= score ? color : 'var(--border)',
            transition: 'background 0.2s',
          }} />
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <span style={{ color }}>{ready ? label : '…'}</span>
        {feedback && <span style={{ color: 'var(--text-muted)' }}>{feedback}</span>}
      </div>
    </div>
  )
}

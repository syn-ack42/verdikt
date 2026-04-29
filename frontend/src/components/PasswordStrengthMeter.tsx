import { useMemo } from 'react'
import { zxcvbn, zxcvbnOptions } from '@zxcvbn-ts/core'
import * as zxcvbnCommonPackage from '@zxcvbn-ts/language-common'
import * as zxcvbnEnPackage from '@zxcvbn-ts/language-en'

zxcvbnOptions.setOptions({
  translations: zxcvbnEnPackage.translations,
  graphs: zxcvbnCommonPackage.adjacencyGraphs,
  dictionary: {
    ...zxcvbnCommonPackage.dictionary,
    ...zxcvbnEnPackage.dictionary,
  },
})

const SCORE_LABELS = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong']
const SCORE_COLORS = ['#c00', '#e05000', '#c08020', '#2e7d32', '#1b5e20']

interface Props {
  password: string
  style?: React.CSSProperties
}

export function scorePassword(password: string): { score: number; feedback: string } {
  if (!password) return { score: 0, feedback: '' }
  const result = zxcvbn(password)
  const warning = result.feedback.warning || ''
  const suggestion = result.feedback.suggestions?.[0] || ''
  const feedback = warning || suggestion
  return { score: result.score, feedback }
}

export default function PasswordStrengthMeter({ password, style }: Props) {
  const { score, feedback } = useMemo(() => scorePassword(password), [password])

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
        <span style={{ color }}>{label}</span>
        {feedback && <span style={{ color: 'var(--text-muted)' }}>{feedback}</span>}
      </div>
    </div>
  )
}

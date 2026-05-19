import { useRef, useEffect } from 'react'

interface PromptEditorProps {
  value: string
  onChange: (v: string) => void
  tokens: string[]          // available {{TOKEN}} names (without braces)
  rows?: number
}

const TOKEN_RE = /\{\{([A-Z_]+)\}\}/g

// Escape HTML for the mirror div
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

// Build the highlighted HTML for the mirror layer
function buildHighlighted(text: string, knownTokens: Set<string>): string {
  const escaped = escapeHtml(text)
  const result = escaped.replace(/\{\{([A-Z_]+)\}\}/g, (match, name) => {
    const known = knownTokens.has(name)
    const bg = known ? 'rgba(107,125,224,0.18)' : 'rgba(200,0,0,0.15)'
    const color = known ? '#4755b8' : '#a00'
    return (
      `<mark style="background:${bg};color:${color};border-radius:3px;padding:0 2px;font-weight:600;">${escapeHtml(match)}</mark>`
    )
  })
  // Preserve trailing newline so mirror height matches textarea
  return result + '​'
}

export default function PromptEditor({ value, onChange, tokens, rows = 10 }: PromptEditorProps) {
  const mirrorRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const knownTokens = new Set(tokens)

  // Keep mirror HTML in sync
  useEffect(() => {
    if (mirrorRef.current) {
      mirrorRef.current.innerHTML = buildHighlighted(value, knownTokens)
    }
  })

  const usedTokens = new Set<string>()
  let m: RegExpExecArray | null
  TOKEN_RE.lastIndex = 0
  while ((m = TOKEN_RE.exec(value)) !== null) usedTokens.add(m[1])

  const sharedStyle: React.CSSProperties = {
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
    fontSize: 13,
    lineHeight: 1.55,
    padding: '8px 10px',
    margin: 0,
    border: 'none',
    width: '100%',
    boxSizing: 'border-box',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    overflowWrap: 'break-word',
    tabSize: 4,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Editor with highlight overlay */}
      <div style={{ position: 'relative', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', overflow: 'hidden' }}>
        {/* Mirror div: renders highlighted text behind the textarea */}
        <div
          ref={mirrorRef}
          aria-hidden
          style={{
            ...sharedStyle,
            position: 'absolute',
            inset: 0,
            pointerEvents: 'none',
            color: 'transparent',
            overflow: 'hidden',
          }}
        />
        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => onChange(e.target.value)}
          rows={rows}
          spellCheck={false}
          style={{
            ...sharedStyle,
            position: 'relative',
            background: 'transparent',
            color: 'var(--text)',
            resize: 'vertical',
            outline: 'none',
            caretColor: 'var(--text)',
          }}
        />
      </div>

      {/* Token pills */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        {tokens.map(tok => {
          const used = usedTokens.has(tok)
          return (
            <span
              key={tok}
              title={used ? 'Used in this prompt' : 'Available — click to insert'}
              onClick={() => {
                if (!textareaRef.current) return
                const ta = textareaRef.current
                const start = ta.selectionStart
                const end = ta.selectionEnd
                const insert = `{{${tok}}}`
                const next = value.slice(0, start) + insert + value.slice(end)
                onChange(next)
                // Restore cursor after the inserted token
                requestAnimationFrame(() => {
                  ta.focus()
                  ta.setSelectionRange(start + insert.length, start + insert.length)
                })
              }}
              style={{
                cursor: 'pointer',
                fontFamily: 'monospace',
                fontSize: 11,
                padding: '2px 7px',
                borderRadius: 4,
                border: `1px solid ${used ? '#4755b8' : 'var(--border)'}`,
                background: used ? 'rgba(107,125,224,0.12)' : 'var(--bg)',
                color: used ? '#4755b8' : 'var(--text-muted)',
                userSelect: 'none',
              }}
            >
              {`{{${tok}}}`}
            </span>
          )
        })}
      </div>
    </div>
  )
}

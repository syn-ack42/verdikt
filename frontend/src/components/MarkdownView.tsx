/**
 * Minimal Markdown renderer for help content.
 * Handles: headings, paragraphs, bold, italic, inline-code, code blocks,
 * unordered/ordered lists, blockquotes, horizontal rules, links, and tables.
 */

import React from 'react'

interface Props {
  markdown: string
  style?: React.CSSProperties
}

function renderInline(text: string, key?: string | number): React.ReactNode {
  // Process inline marks: **bold**, *italic*, `code`, [label](url)
  const parts: React.ReactNode[] = []
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g
  let last = 0
  let m: RegExpExecArray | null
  let idx = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[2] !== undefined) parts.push(<strong key={idx++}>{m[2]}</strong>)
    else if (m[3] !== undefined) parts.push(<em key={idx++}>{m[3]}</em>)
    else if (m[4] !== undefined) parts.push(<code key={idx++} style={{ background: 'var(--surface, rgba(128,128,128,0.12))', padding: '1px 5px', borderRadius: 3, fontSize: '0.88em', fontFamily: 'monospace' }}>{m[4]}</code>)
    else if (m[5] !== undefined) parts.push(<a key={idx++} href={m[6]} target="_blank" rel="noopener noreferrer" style={{ color: '#6b7de0' }}>{m[5]}</a>)
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <React.Fragment key={key}>{parts}</React.Fragment>
}

export default function MarkdownView({ markdown, style }: Props) {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const nodes: React.ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim()
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++ // consume closing ```
      nodes.push(
        <pre key={key++} style={{ background: 'var(--surface, rgba(128,128,128,0.08))', border: '1px solid var(--border)', borderRadius: 6, padding: '12px 14px', overflowX: 'auto', margin: '12px 0', fontSize: 13, lineHeight: 1.5 }}>
          <code>{codeLines.join('\n')}</code>
        </pre>
      )
      continue
    }

    // Headings
    const h3 = line.match(/^###\s+(.+)/)
    if (h3) { nodes.push(<h3 key={key++} style={{ margin: '20px 0 6px', fontSize: 15, fontWeight: 600 }}>{renderInline(h3[1])}</h3>); i++; continue }
    const h2 = line.match(/^##\s+(.+)/)
    if (h2) { nodes.push(<h2 key={key++} style={{ margin: '24px 0 8px', fontSize: 17, fontWeight: 700, borderBottom: '1px solid var(--border)', paddingBottom: 6 }}>{renderInline(h2[1])}</h2>); i++; continue }
    const h1 = line.match(/^#\s+(.+)/)
    if (h1) { nodes.push(<h1 key={key++} style={{ margin: '0 0 16px', fontSize: 20, fontWeight: 700 }}>{renderInline(h1[1])}</h1>); i++; continue }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) { nodes.push(<hr key={key++} style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '16px 0' }} />); i++; continue }

    // Blockquote
    if (line.startsWith('> ')) {
      const bqLines: string[] = []
      while (i < lines.length && lines[i].startsWith('> ')) { bqLines.push(lines[i].slice(2)); i++ }
      nodes.push(<blockquote key={key++} style={{ margin: '12px 0', paddingLeft: 12, borderLeft: '3px solid var(--border)', color: 'var(--text-muted)', fontStyle: 'italic' }}>{bqLines.map((l, j) => <React.Fragment key={j}>{renderInline(l)}{j < bqLines.length - 1 && <br />}</React.Fragment>)}</blockquote>)
      continue
    }

    // Table
    if (line.startsWith('|')) {
      const tableLines: string[] = []
      while (i < lines.length && lines[i].startsWith('|')) { tableLines.push(lines[i]); i++ }
      const parseRow = (r: string) => r.split('|').slice(1, -1).map(c => c.trim())
      const headers = parseRow(tableLines[0])
      const bodyRows = tableLines.slice(2) // skip separator
      nodes.push(
        <div key={key++} style={{ overflowX: 'auto', margin: '12px 0' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
            <thead>
              <tr>{headers.map((h, j) => <th key={j} style={{ textAlign: 'left', padding: '6px 12px', borderBottom: '2px solid var(--border)', fontWeight: 600, whiteSpace: 'nowrap' }}>{renderInline(h)}</th>)}</tr>
            </thead>
            <tbody>
              {bodyRows.map((r, ri) => (
                <tr key={ri} style={{ background: ri % 2 === 0 ? 'transparent' : 'var(--surface, rgba(128,128,128,0.04))' }}>
                  {parseRow(r).map((c, ci) => <td key={ci} style={{ padding: '6px 12px', borderBottom: '1px solid var(--border)' }}>{renderInline(c)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    // Unordered list
    if (/^[-*+]\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) { items.push(lines[i].slice(2)); i++ }
      nodes.push(<ul key={key++} style={{ margin: '8px 0', paddingLeft: 24, lineHeight: 1.7 }}>{items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>)
      continue
    }

    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) { items.push(lines[i].replace(/^\d+\.\s/, '')); i++ }
      nodes.push(<ol key={key++} style={{ margin: '8px 0', paddingLeft: 24, lineHeight: 1.7 }}>{items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ol>)
      continue
    }

    // Blank line — skip
    if (line.trim() === '') { i++; continue }

    // Paragraph — collect until blank line or block-level element
    const paraLines: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('#') &&
      !lines[i].startsWith('```') &&
      !lines[i].startsWith('> ') &&
      !lines[i].startsWith('|') &&
      !/^[-*+]\s/.test(lines[i]) &&
      !/^\d+\.\s/.test(lines[i]) &&
      !/^---+$/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i])
      i++
    }
    if (paraLines.length > 0) {
      nodes.push(
        <p key={key++} style={{ margin: '8px 0', lineHeight: 1.7 }}>
          {paraLines.map((l, j) => (
            <React.Fragment key={j}>
              {renderInline(l)}
              {j < paraLines.length - 1 && <br />}
            </React.Fragment>
          ))}
        </p>
      )
    }
  }

  return <div style={{ fontSize: 14, color: 'var(--text)', ...style }}>{nodes}</div>
}

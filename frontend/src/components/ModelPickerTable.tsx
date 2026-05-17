import { useState } from 'react'
import type { ModelCatalogEntry } from '../api/types'

interface Props {
  models: ModelCatalogEntry[]
  selectedId: string | null
  isPersonalSelected: boolean
  onSelect: (id: string | null, isPersonal: boolean) => void
  noneLabel?: string
  listMaxHeight?: number
}

const COLS = '18px 1fr 55px 90px'
type SortKey = 'display_name' | 'parameter_size' | 'input_cost_usd_per_mtok'

function RadioDot({ selected }: { selected: boolean }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 14, height: 14, borderRadius: '50%', flexShrink: 0, marginTop: 2,
      border: `2px solid ${selected ? '#6b7de0' : 'var(--border)'}`,
      background: selected ? '#6b7de0' : 'transparent',
    }}>
      {selected && <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#fff' }} />}
    </span>
  )
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: `${color}22`, color, fontWeight: 600, letterSpacing: 0.3, flexShrink: 0 }}>
      {label}
    </span>
  )
}

function rowOuter(selected: boolean): React.CSSProperties {
  return {
    cursor: 'pointer',
    background: selected ? 'rgba(107,125,224,0.10)' : 'transparent',
    borderLeft: `3px solid ${selected ? '#6b7de0' : 'transparent'}`,
  }
}

function applySort(models: ModelCatalogEntry[], by: SortKey, dir: 'asc' | 'desc') {
  return [...models].sort((a, b) => {
    let av: string | number, bv: string | number
    if (by === 'display_name') { av = a.display_name.toLowerCase(); bv = b.display_name.toLowerCase() }
    else if (by === 'parameter_size') { av = a.parameter_size ?? ''; bv = b.parameter_size ?? '' }
    else { av = a.input_cost_usd_per_mtok ?? Infinity; bv = b.input_cost_usd_per_mtok ?? Infinity }
    if (av < bv) return dir === 'asc' ? -1 : 1
    if (av > bv) return dir === 'asc' ? 1 : -1
    return 0
  })
}

function sortSelectedFirst(models: ModelCatalogEntry[], isRowSelected: (m: ModelCatalogEntry, personal: boolean) => boolean, isPersonal: boolean) {
  const idx = models.findIndex(m => isRowSelected(m, isPersonal))
  if (idx <= 0) return models
  return [models[idx], ...models.slice(0, idx), ...models.slice(idx + 1)]
}

export default function ModelPickerTable({
  models, selectedId, isPersonalSelected, onSelect, noneLabel, listMaxHeight = 260,
}: Props) {
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<SortKey>('display_name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const toggleSort = (col: SortKey) => {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortDir('asc') }
  }

  const sortHeader = (col: SortKey, label: string) => (
    <span
      onClick={() => toggleSort(col)}
      style={{ cursor: 'pointer', userSelect: 'none', display: 'inline-flex', alignItems: 'center', gap: 3 }}
    >
      {label}
      <span style={{ fontSize: 9, opacity: sortBy === col ? 1 : 0.3 }}>
        {sortBy === col ? (sortDir === 'asc' ? '▲' : '▼') : '▲'}
      </span>
    </span>
  )

  const q = search.trim().toLowerCase()
  const filtered = models.filter(m =>
    !q || m.display_name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q) || (m.description ?? '').toLowerCase().includes(q)
  )
  const sorted = applySort(filtered, sortBy, sortDir)

  const isNoneSelected = !selectedId && !isPersonalSelected
  const isRowSelected = (m: ModelCatalogEntry, personal: boolean) =>
    m.id === selectedId && personal === isPersonalSelected

  const hover = (e: React.MouseEvent<HTMLDivElement>, enter: boolean, selected: boolean) => {
    if (!selected) e.currentTarget.style.background = enter ? 'var(--surface, rgba(128,128,128,0.04))' : 'transparent'
  }

  // Groups
  const siteModels = sortSelectedFirst(sorted.filter(m => !m.personal_only), isRowSelected, false)
  const venicePersonal = sortSelectedFirst(sorted.filter(m => m.personal_only && m.source === 'venice'), isRowSelected, true)
  const openRouterPersonal = sortSelectedFirst(sorted.filter(m => m.personal_only && m.source === 'openrouter'), isRowSelected, true)
  const hasPersonalGroups = venicePersonal.length > 0 || openRouterPersonal.length > 0

  const siteHasSelected = isNoneSelected || siteModels.some(m => isRowSelected(m, false))
  const veniceHasSelected = venicePersonal.some(m => isRowSelected(m, true))
  const openRouterHasSelected = openRouterPersonal.some(m => isRowSelected(m, true))

  const hasRows = siteModels.length + venicePersonal.length + openRouterPersonal.length > 0

  const renderRow = (m: ModelCatalogEntry, isPersonal: boolean, last: boolean) => {
    const selected = isRowSelected(m, isPersonal)
    return (
      <div
        key={isPersonal ? `p:${m.id}` : m.id}
        onClick={() => onSelect(m.id, isPersonal)}
        style={{ ...rowOuter(selected), borderBottom: last ? 'none' : '1px solid var(--border)' }}
        onMouseEnter={e => hover(e, true, selected)}
        onMouseLeave={e => hover(e, false, selected)}
      >
        {/* Main grid row */}
        <div style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '9px 12px 4px 10px', alignItems: 'start' }}>
          <RadioDot selected={selected} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 500, fontSize: 13 }}>{m.display_name}</span>
              {isPersonal && m.source === 'openrouter' && <Badge label="OpenRouter · Personal" color="#0ea5e9" />}
              {isPersonal && m.source !== 'openrouter' && <Badge label="Venice · Personal" color="#7c3aed" />}
              {!isPersonal && m.source === 'venice' && <Badge label="Charged via site" color="#7c3aed" />}
              {!isPersonal && m.source === 'openrouter' && <Badge label="Charged via site" color="#0ea5e9" />}
              {!isPersonal && m.source !== 'venice' && m.source !== 'openrouter' && <Badge label="Local" color="#666" />}
              {m.is_default && !isPersonal && <Badge label="★ Default" color="#c08020" />}
              {m.privacy === 'private' && (
                <span title="Venice does not log or retain prompts" style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'rgba(5,150,105,0.12)', color: '#059669', fontWeight: 600, letterSpacing: 0.3, flexShrink: 0 }}>🔒 Private</span>
              )}
              {m.privacy === 'anonymized' && (
                <span title="Prompts may be retained in anonymized form" style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'rgba(180,83,9,0.12)', color: '#b45309', fontWeight: 600, letterSpacing: 0.3, flexShrink: 0 }}>〜 Anon</span>
              )}
            </div>
            {m.id !== m.display_name && (
              <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.id}</span>
            )}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span>{m.parameter_size ?? (m.context_length ? '' : '—')}</span>
            {m.context_length != null && <span style={{ fontSize: 10 }}>{(m.context_length / 1000).toFixed(0)}k</span>}
          </div>
          <div style={{ fontSize: 11, display: 'flex', flexDirection: 'column', gap: 1 }}>
            {m.input_cost_usd_per_mtok != null ? (
              <>
                <span title="Input cost per million tokens">${m.input_cost_usd_per_mtok.toFixed(2)} in</span>
                <span style={{ color: 'var(--text-muted)' }} title="Output cost per million tokens">${m.output_cost_usd_per_mtok?.toFixed(2) ?? '?'} out</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>per Mtok</span>
              </>
            ) : (
              <span style={{ color: 'var(--text-muted)' }}>—</span>
            )}
          </div>
        </div>
        {/* Description — full width below grid */}
        {m.description && (
          <div style={{ padding: '1px 12px 7px 39px', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>
            {m.description}
          </div>
        )}
      </div>
    )
  }

  const groupHeader = (label: string, color: string, hasSelected: boolean, extraStyle?: React.CSSProperties) => (
    <div style={{
      padding: '5px 10px', fontSize: 11, fontWeight: 600, letterSpacing: 0.2,
      color: hasSelected ? color : 'var(--text-muted)',
      background: hasSelected ? `${color}0d` : 'var(--surface, rgba(128,128,128,0.04))',
      borderTop: '1px solid var(--border)',
      borderBottom: '1px solid var(--border)',
      borderLeft: hasSelected ? `3px solid ${color}` : '3px solid transparent',
      display: 'flex', alignItems: 'center', gap: 6,
      ...extraStyle,
    }}>
      {hasSelected && <span style={{ fontSize: 9 }}>●</span>}
      {label}
    </div>
  )

  return (
    <>
      {/* Search — outside scroll so it stays pinned */}
      <input
        type="search"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Search models…"
        style={{
          width: '100%', boxSizing: 'border-box', padding: '6px 10px', marginBottom: 6,
          borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)',
          color: 'var(--text)', fontSize: 13,
        }}
      />

      {/* Border wrapper — column header outside scroll */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        {/* Column header */}
        <div style={{
          display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '5px 12px 5px 10px',
          fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5,
          color: 'var(--text-muted)', background: 'var(--surface, rgba(128,128,128,0.04))',
          borderBottom: '1px solid var(--border)',
        }}>
          <span />
          {sortHeader('display_name', 'Model')}
          {sortHeader('parameter_size', 'Size')}
          {sortHeader('input_cost_usd_per_mtok', 'Cost/Mtok')}
        </div>

        {/* Scrollable rows */}
        <div style={{ maxHeight: listMaxHeight, overflowY: 'auto' }}>
          {!hasRows && (
            <p style={{ margin: '10px 12px', fontSize: 13, color: 'var(--text-muted)' }}>
              {search ? `No models match "${search}".` : 'No models available for this domain.'}
            </p>
          )}

          {/* None / auto row */}
          {noneLabel && (() => {
            const selected = isNoneSelected
            const last = siteModels.length === 0 && !hasPersonalGroups
            return (
              <div
                onClick={() => onSelect(null, false)}
                style={{ ...rowOuter(selected), borderBottom: last ? 'none' : '1px solid var(--border)' }}
                onMouseEnter={e => hover(e, true, selected)}
                onMouseLeave={e => hover(e, false, selected)}
              >
                <div style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, padding: '9px 12px 9px 10px', alignItems: 'center' }}>
                  <RadioDot selected={selected} />
                  <span style={{ fontSize: 13, fontStyle: 'italic', color: selected ? 'var(--text)' : 'var(--text-muted)', gridColumn: '2 / -1' }}>
                    {noneLabel}
                  </span>
                </div>
              </div>
            )
          })()}

          {/* Site group header — only shown when personal groups exist */}
          {hasPersonalGroups && siteModels.length > 0 && groupHeader('Site — admin managed', '#6b7de0', siteHasSelected, { borderTop: 'none' })}

          {siteModels.map((m, i) => renderRow(m, false, !hasPersonalGroups && i === siteModels.length - 1))}

          {/* Venice personal group */}
          {venicePersonal.length > 0 && groupHeader('Venice · Personal key', '#7c3aed', veniceHasSelected)}
          {venicePersonal.map((m, i) => renderRow(m, true, openRouterPersonal.length === 0 && i === venicePersonal.length - 1))}

          {/* OpenRouter personal group */}
          {openRouterPersonal.length > 0 && groupHeader('OpenRouter · Personal key', '#0ea5e9', openRouterHasSelected)}
          {openRouterPersonal.map((m, i) => renderRow(m, true, i === openRouterPersonal.length - 1))}
        </div>
      </div>
    </>
  )
}

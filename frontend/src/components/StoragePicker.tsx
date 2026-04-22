import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { StorageEntry } from '../api/types'

export interface Selection {
  path: string
  mode: 'folder' | 'file'
}

interface Props {
  value: Selection[]
  onChange: (selections: Selection[]) => void
}

type CheckState = 'checked' | 'partial' | 'unchecked'

function getCheckState(path: string, isDir: boolean, selections: Selection[]): CheckState {
  if (isDir) {
    const exact = selections.find(s => s.path === path && s.mode === 'folder')
    if (exact) return 'checked'
    const hasDescendant = selections.some(s => s.path.startsWith(path + '/'))
    if (hasDescendant) return 'partial'
    return 'unchecked'
  } else {
    return selections.some(s => s.path === path) ? 'checked' : 'unchecked'
  }
}

function isCoveredByAncestor(path: string, selections: Selection[]): boolean {
  return selections.some(s => s.mode === 'folder' && path.startsWith(s.path + '/'))
}

function Checkbox({ state, covered, onClick }: { state: CheckState; covered: boolean; onClick: () => void }) {
  const style: React.CSSProperties = {
    width: 15, height: 15, flexShrink: 0, cursor: covered ? 'default' : 'pointer',
    accentColor: '#6b7de0', opacity: covered ? 0.5 : 1,
  }
  if (state === 'partial') {
    return (
      <span
        onClick={covered ? undefined : onClick}
        style={{
          ...style, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          border: '2px solid #6b7de0', borderRadius: 3, background: 'transparent',
        }}
        title={covered ? 'Covered by parent folder' : undefined}
      >
        <span style={{ width: 7, height: 2, background: '#6b7de0', display: 'block' }} />
      </span>
    )
  }
  return (
    <input
      type="checkbox"
      checked={state === 'checked'}
      onChange={covered ? undefined : onClick}
      onClick={covered ? undefined : onClick}
      style={style}
      title={covered ? 'Covered by parent folder' : undefined}
      readOnly={covered}
    />
  )
}

interface NodeProps {
  entry: StorageEntry
  selections: Selection[]
  onToggle: (path: string, isDir: boolean) => void
}

function StorageNode({ entry, selections, onToggle }: NodeProps) {
  const [expanded, setExpanded] = useState(false)
  const covered = isCoveredByAncestor(entry.path, selections)
  const checkState = covered ? 'checked' : getCheckState(entry.path, entry.is_dir, selections)

  const { data: children } = useQuery({
    queryKey: ['storage', entry.path],
    queryFn: () => api.storage.list(entry.path),
    enabled: entry.is_dir && expanded,
  })

  return (
    <div style={{ userSelect: 'none' }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0',
          cursor: 'default',
        }}
      >
        {entry.is_dir ? (
          <span
            onClick={() => setExpanded(e => !e)}
            style={{ fontSize: 11, color: 'var(--text-muted)', width: 14, textAlign: 'center', cursor: 'pointer', flexShrink: 0 }}
          >
            {expanded ? '▾' : '▸'}
          </span>
        ) : (
          <span style={{ width: 14, flexShrink: 0 }} />
        )}
        <Checkbox
          state={checkState}
          covered={covered}
          onClick={() => !covered && onToggle(entry.path, entry.is_dir)}
        />
        <span
          onClick={entry.is_dir ? () => setExpanded(e => !e) : undefined}
          style={{
            fontSize: 13, cursor: entry.is_dir ? 'pointer' : 'default',
            color: entry.is_dir ? 'var(--text)' : 'var(--text-muted)',
          }}
        >
          {entry.is_dir ? '📁' : '📄'} {entry.name}
        </span>
        {!entry.is_dir && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
            {(entry.size / 1024).toFixed(0)} KB
          </span>
        )}
        {entry.is_dir && checkState === 'checked' && !covered && (
          <span style={{ fontSize: 11, color: '#6b7de0', marginLeft: 'auto' }}>whole folder</span>
        )}
      </div>

      {entry.is_dir && expanded && (
        <div style={{ marginLeft: 22, borderLeft: '1px solid var(--border)', paddingLeft: 8 }}>
          {children?.entries.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '4px 0' }}>Empty folder</div>
          )}
          {children?.entries.map(child => (
            <StorageNode key={child.path} entry={child} selections={selections} onToggle={onToggle} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function StoragePicker({ value, onChange }: Props) {
  const { data: root, isLoading } = useQuery({
    queryKey: ['storage', '/'],
    queryFn: () => api.storage.list('/'),
  })

  const handleToggle = (path: string, isDir: boolean) => {
    const existing = value.find(s => s.path === path)
    if (existing) {
      onChange(value.filter(s => s.path !== path))
    } else {
      onChange([...value, { path, mode: isDir ? 'folder' : 'file' }])
    }
  }

  const selectedFolders = value.filter(s => s.mode === 'folder')
  const selectedFiles = value.filter(s => s.mode === 'file')

  return (
    <div>
      {value.length > 0 && (
        <div style={{
          marginBottom: 10, padding: '8px 10px', background: 'var(--surface)',
          border: '1px solid var(--border)', borderRadius: 6, fontSize: 12, color: 'var(--text-muted)',
        }}>
          {selectedFolders.length > 0 && (
            <div>📁 {selectedFolders.length} folder{selectedFolders.length !== 1 ? 's' : ''} (whole, includes new files)</div>
          )}
          {selectedFiles.length > 0 && (
            <div>📄 {selectedFiles.length} specific file{selectedFiles.length !== 1 ? 's' : ''}</div>
          )}
        </div>
      )}

      <div style={{
        border: '1px solid var(--border)', borderRadius: 6,
        padding: '8px 10px', maxHeight: 320, overflowY: 'auto',
        background: 'var(--bg)',
      }}>
        {isLoading && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading storage…</div>}
        {root?.entries.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            Storage is empty. Upload files via Settings → Storage.
          </div>
        )}
        {root?.entries.map(entry => (
          <StorageNode key={entry.path} entry={entry} selections={value} onToggle={handleToggle} />
        ))}
      </div>
    </div>
  )
}

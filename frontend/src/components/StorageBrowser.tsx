import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { modalChrome } from '../styles'
import type { StorageEntry } from '../api/types'

import type { IngestResult } from '../api/types'

interface Props {
  onIngest: (paths: string[]) => void
  ingesting: boolean
  ingestResult?: IngestResult | null
  ingestError?: string | null
  onClose: () => void
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function Breadcrumbs({ path, onNavigate }: { path: string; onNavigate: (p: string) => void }) {
  const parts = path === '/' ? [] : path.split('/').filter(Boolean)
  return (
    <div style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 13, flexWrap: 'wrap' }}>
      <button
        onClick={() => onNavigate('/')}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: '2px 4px' }}
      >
        /
      </button>
      {parts.map((part, i) => {
        const target = '/' + parts.slice(0, i + 1).join('/')
        return (
          <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: 'var(--text-muted)' }}>›</span>
            <button
              onClick={() => onNavigate(target)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: i === parts.length - 1 ? 'var(--text)' : '#6b7de0',
                fontWeight: i === parts.length - 1 ? 600 : 400,
                padding: '2px 4px',
              }}
            >
              {part}
            </button>
          </span>
        )
      })}
    </div>
  )
}

export default function StorageBrowser({ onIngest, ingesting, ingestResult, ingestError, onClose }: Props) {
  const qc = useQueryClient()
  const [currentPath, setCurrentPath] = useState('/')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [newFolderName, setNewFolderName] = useState('')
  const [showNewFolder, setShowNewFolder] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['storage', currentPath],
    queryFn: () => api.storage.list(currentPath),
  })

  const upload = useMutation({
    mutationFn: (files: FileList) => api.storage.upload(currentPath, files),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage', currentPath] }),
  })

  const mkdir = useMutation({
    mutationFn: () => {
      const name = newFolderName.trim().replace(/[/\\]/g, '')
      if (!name) throw new Error('Folder name cannot be empty')
      const target = currentPath.replace(/\/$/, '') + '/' + name
      return api.storage.mkdir(target)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['storage', currentPath] })
      setNewFolderName('')
      setShowNewFolder(false)
    },
  })

  const del = useMutation({
    mutationFn: (path: string) => api.storage.delete(path),
    onSuccess: (_data, path) => {
      setSelected(prev => { const next = new Set(prev); next.delete(path); return next })
      qc.invalidateQueries({ queryKey: ['storage', currentPath] })
    },
  })

  const navigate = (path: string) => {
    setCurrentPath(path)
    setSelected(new Set())
  }

  const toggleSelect = (path: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const allChecked = data?.entries.length
    ? data.entries.every(e => selected.has(e.path))
    : false

  const toggleAll = () => {
    if (allChecked) {
      setSelected(new Set())
    } else {
      setSelected(new Set(data?.entries.map(e => e.path) ?? []))
    }
  }

  const entries: StorageEntry[] = data?.entries ?? []

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ ...modalChrome, width: 680, maxHeight: '80vh' }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Storage</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}>×</button>
        </div>

        {/* Toolbar */}
        <div style={{ padding: '10px 20px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Breadcrumbs path={currentPath} onNavigate={navigate} />
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button
              onClick={() => setShowNewFolder(v => !v)}
              style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4, cursor: 'pointer' }}
            >
              New folder
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={upload.isPending}
              style={{ fontSize: 12, padding: '4px 10px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
            >
              {upload.isPending ? 'Uploading…' : 'Upload files'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              style={{ display: 'none' }}
              onChange={e => e.target.files && upload.mutate(e.target.files)}
            />
          </div>
        </div>

        {/* New folder input */}
        {showNewFolder && (
          <div style={{ padding: '8px 20px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8 }}>
            <input
              autoFocus
              placeholder="Folder name"
              value={newFolderName}
              onChange={e => setNewFolderName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') mkdir.mutate() }}
              style={{ flex: 1, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--text)' }}
            />
            <button onClick={() => mkdir.mutate()} disabled={mkdir.isPending} style={{ padding: '4px 12px' }}>
              Create
            </button>
            <button onClick={() => setShowNewFolder(false)} style={{ padding: '4px 8px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>
              Cancel
            </button>
            {mkdir.error && <span style={{ color: '#c00', fontSize: 12, alignSelf: 'center' }}>{String(mkdir.error)}</span>}
          </div>
        )}

        {/* Upload feedback */}
        {upload.data && (
          <div style={{ padding: '4px 20px', background: 'var(--badge-green-bg)', fontSize: 12, color: 'var(--badge-green-text)' }}>
            Uploaded: {upload.data.uploaded.join(', ')}
          </div>
        )}

        {/* File list */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {isLoading && <p style={{ padding: 20, color: 'var(--text-muted)' }}>Loading…</p>}
          {error && <p style={{ padding: 20, color: '#c00' }}>Error loading directory</p>}
          {!isLoading && entries.length === 0 && (
            <p style={{ padding: 20, color: 'var(--text-muted)', textAlign: 'center' }}>
              Empty folder — upload files to get started
            </p>
          )}
          {entries.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
                  <th style={{ padding: '6px 8px 6px 16px', textAlign: 'left', width: 32 }}>
                    <input type="checkbox" checked={allChecked} onChange={toggleAll} />
                  </th>
                  <th style={{ padding: '6px 8px', textAlign: 'left' }}>Name</th>
                  <th style={{ padding: '6px 8px', textAlign: 'right', width: 80 }}>Size</th>
                  <th style={{ padding: '6px 8px', textAlign: 'left', width: 100 }}>Modified</th>
                  <th style={{ padding: '6px 8px', width: 40 }}></th>
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => (
                  <tr
                    key={entry.path}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: selected.has(entry.path) ? 'rgba(107,125,224,0.12)' : 'transparent',
                    }}
                  >
                    <td style={{ padding: '6px 8px 6px 16px' }}>
                      <input
                        type="checkbox"
                        checked={selected.has(entry.path)}
                        onChange={() => toggleSelect(entry.path)}
                      />
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      {entry.is_dir ? (
                        <button
                          onClick={() => navigate(entry.path)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text)', padding: 0, textAlign: 'left' }}
                        >
                          📁 {entry.name}
                        </button>
                      ) : (
                        <span>📄 {entry.name}</span>
                      )}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--text-muted)' }}>
                      {entry.is_dir ? '—' : formatSize(entry.size)}
                    </td>
                    <td style={{ padding: '6px 8px', color: 'var(--text-muted)' }}>
                      {entry.modified_at.slice(0, 10)}
                    </td>
                    <td style={{ padding: '6px 8px', textAlign: 'center' }}>
                      <button
                        onClick={() => confirm(`Delete "${entry.name}"?`) && del.mutate(entry.path)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 14 }}
                        title="Delete"
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)' }}>
          {ingestError && (
            <p style={{ margin: '0 0 8px', fontSize: 13, color: '#c00' }}>{ingestError}</p>
          )}
          {ingestResult && ingestResult.added + ingestResult.updated === 0 && (
            <p style={{ margin: '0 0 8px', fontSize: 13, color: '#b45309' }}>
              {ingestResult.skipped > 0
                ? `${ingestResult.skipped} file${ingestResult.skipped > 1 ? 's' : ''} already ingested — nothing changed.`
                : 'No supported files found. Supported formats: .txt, .md, .html, .epub, .pdf, .rtf'}
            </p>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {selected.size > 0 ? `${selected.size} selected` : 'Select files or folders to ingest'}
            </span>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={onClose} style={{ padding: '6px 14px', borderRadius: 4, cursor: 'pointer' }}>
                {ingestResult && ingestResult.added + ingestResult.updated === 0 ? 'Close' : 'Cancel'}
              </button>
              <button
                onClick={() => onIngest(Array.from(selected))}
                disabled={selected.size === 0 || ingesting}
                style={{
                  padding: '6px 16px',
                  background: selected.size > 0 ? '#6b7de0' : 'var(--border)',
                  color: selected.size > 0 ? '#fff' : 'var(--text-muted)',
                  border: 'none', borderRadius: 4,
                  cursor: selected.size > 0 ? 'pointer' : 'default',
                }}
              >
                {ingesting ? 'Ingesting…' : `Ingest ${selected.size > 0 ? selected.size + ' item' + (selected.size > 1 ? 's' : '') : ''}`}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

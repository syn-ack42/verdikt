import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

interface Props {
  projectId: string
  workRef: string | number
  onClose: () => void
}

export default function WorkDetailModal({ projectId, workRef, onClose }: Props) {
  const { data: work, isLoading, error } = useQuery({
    queryKey: ['work-detail', projectId, workRef],
    queryFn: () => api.works.detail(projectId, String(workRef)),
  })

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--modal-bg)', color: 'var(--text)',
        borderRadius: 10, width: 780, maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)', overflow: 'hidden',
        border: '1px solid var(--border)',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 16, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {work?.work_title ?? (isLoading ? 'Loading…' : 'Work Detail')}
            </h3>
            {work?.author && <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{work.author}</p>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)', flexShrink: 0 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}
          {error && <p style={{ color: '#c00' }}>Failed to load work details.</p>}

          {work && (
            <>
              <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
                <tbody>
                  <MetaRow label="Source">{work.source_plugin}</MetaRow>
                  <MetaRow label="Status">
                    <span style={{
                      background: work.pipeline_phase === 'clustered' ? 'var(--badge-green-bg)' : 'var(--badge-yellow-bg)',
                      color: work.pipeline_phase === 'clustered' ? 'var(--badge-green-text)' : 'var(--badge-yellow-text)',
                      padding: '1px 6px', borderRadius: 3, fontSize: 11,
                    }}>
                      {work.pipeline_phase === 'clustered' ? 'processed' : work.pipeline_phase}
                    </span>
                  </MetaRow>
                  <MetaRow label="Ingested">{work.ingested_at.slice(0, 10)}</MetaRow>
                  {work.content_hash && (
                    <MetaRow label="Hash">
                      <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{work.content_hash.slice(0, 16)}…</span>
                    </MetaRow>
                  )}

                  {/* AO3-specific */}
                  {work.source_plugin === 'ao3' && work.plugin_metadata.work_id && (
                    <MetaRow label="Work ID">{String(work.plugin_metadata.work_id)}</MetaRow>
                  )}
                  {work.source_plugin === 'ao3' && work.plugin_metadata.source_updated_at && (
                    <MetaRow label="Last updated">{String(work.plugin_metadata.source_updated_at).slice(0, 10)}</MetaRow>
                  )}
                  {work.source_plugin === 'ao3' && work.url && (
                    <MetaRow label="URL">
                      <a href={work.url} target="_blank" rel="noopener noreferrer"
                        style={{ color: '#6b7de0', wordBreak: 'break-all' }}>
                        {work.url}
                      </a>
                    </MetaRow>
                  )}

                  {/* filedrop-specific */}
                  {work.source_plugin === 'filedrop' && (
                    <MetaRow label="File">
                      <span style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                        {work.storage_path ?? work.source_path}
                      </span>
                      {work.storage_path && (
                        <a href={api.storage.downloadUrl(work.storage_path)} download
                          style={{ marginLeft: 10, fontSize: 12, padding: '2px 8px', background: '#6b7de0', color: '#fff', borderRadius: 4, textDecoration: 'none' }}>
                          Download
                        </a>
                      )}
                    </MetaRow>
                  )}

                  {/* Generic fallback for unknown plugins */}
                  {work.source_plugin !== 'ao3' && work.source_plugin !== 'filedrop' &&
                    Object.entries(work.plugin_metadata).map(([k, v]) => v != null && v !== '' ? (
                      <MetaRow key={k} label={k}>
                        <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{String(v)}</span>
                      </MetaRow>
                    ) : null)
                  }
                </tbody>
              </table>

              {/* Full content */}
              <div>
                <h4 style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Full Content
                </h4>
                {work.content ? (
                  <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6,
                    padding: '12px 16px', maxHeight: 480, overflowY: 'auto',
                    fontSize: 14, lineHeight: 1.75, whiteSpace: 'pre-wrap',
                    fontFamily: 'Georgia, serif',
                  }}>
                    {work.content}
                  </div>
                ) : (
                  <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>(Binary content — not displayable)</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}


function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '4px 12px 4px 0', color: 'var(--text-muted)', fontWeight: 500, whiteSpace: 'nowrap', verticalAlign: 'top' }}>{label}</td>
      <td style={{ padding: '4px 0' }}>{children}</td>
    </tr>
  )
}

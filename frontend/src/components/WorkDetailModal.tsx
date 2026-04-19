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
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#fff', color: '#1a1a1a', borderRadius: 10,
        width: 780, maxHeight: '90vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0,0,0,0.22)', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 16, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {work?.work_title ?? (isLoading ? 'Loading…' : 'Work Detail')}
            </h3>
            {work?.author && <p style={{ margin: '2px 0 0', fontSize: 13, color: '#666' }}>{work.author}</p>}
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#888', flexShrink: 0 }}>×</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {isLoading && <p style={{ color: '#888' }}>Loading…</p>}
          {error && <p style={{ color: '#c00' }}>Failed to load work details.</p>}

          {work && (
            <>
              {/* Metadata grid */}
              <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
                <tbody>
                  <MetaRow label="Source">{work.source_plugin}</MetaRow>
                  <MetaRow label="Status">
                    <span style={{
                      background: work.pipeline_phase === 'clustered' ? '#e8f5e9' : '#fff8e1',
                      padding: '1px 6px', borderRadius: 3, fontSize: 11,
                    }}>
                      {work.pipeline_phase}
                    </span>
                  </MetaRow>
                  <MetaRow label="Ingested">{work.ingested_at.slice(0, 10)}</MetaRow>
                  {work.content_hash && (
                    <MetaRow label="Hash">
                      <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{work.content_hash.slice(0, 16)}…</span>
                    </MetaRow>
                  )}
                </tbody>
              </table>

              {/* Source-specific links */}
              {work.source_plugin === 'ao3' && work.url && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: '#666', flexShrink: 0 }}>AO3:</span>
                  <a
                    href={work.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ fontSize: 13, color: '#6b7de0', wordBreak: 'break-all' }}
                  >
                    {work.url}
                  </a>
                </div>
              )}

              {work.source_plugin === 'filedrop' && (
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, color: '#666', flexShrink: 0 }}>File:</span>
                  <span style={{ fontSize: 13, fontFamily: 'monospace', color: '#333', wordBreak: 'break-all' }}>
                    {work.storage_path ?? work.source_path}
                  </span>
                  {work.storage_path && (
                    <a
                      href={api.storage.downloadUrl(work.storage_path)}
                      download
                      style={{
                        fontSize: 12, padding: '3px 10px',
                        background: '#6b7de0', color: '#fff',
                        borderRadius: 4, textDecoration: 'none', flexShrink: 0,
                      }}
                    >
                      Download
                    </a>
                  )}
                </div>
              )}

              {/* Full content */}
              <div>
                <h4 style={{ margin: '0 0 8px', fontSize: 13, color: '#555', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Full Content
                </h4>
                {work.content ? (
                  <div style={{
                    background: '#fafafa', border: '1px solid #e0e0e0', borderRadius: 6,
                    padding: '12px 16px', maxHeight: 480, overflowY: 'auto',
                    fontSize: 14, lineHeight: 1.75, whiteSpace: 'pre-wrap',
                    fontFamily: 'Georgia, serif',
                  }}>
                    {work.content}
                  </div>
                ) : (
                  <p style={{ fontSize: 13, color: '#aaa' }}>(Binary content — not displayable)</p>
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
    <tr style={{ borderBottom: '1px solid #f5f5f5' }}>
      <td style={{ padding: '4px 12px 4px 0', color: '#888', fontWeight: 500, whiteSpace: 'nowrap', verticalAlign: 'top' }}>{label}</td>
      <td style={{ padding: '4px 0' }}>{children}</td>
    </tr>
  )
}

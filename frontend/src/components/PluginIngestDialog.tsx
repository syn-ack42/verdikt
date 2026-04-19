import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { IngestResult, PluginInfo, PluginIngestEvent } from '../api/types'
import PluginConfigEditor from './PluginConfigEditor'

interface Props {
  projectId: string
  onClose: () => void
  onSuccess: (result: IngestResult) => void
}

interface LogEntry {
  work: string
  status: 'added' | 'updated' | 'unchanged'
}

function defaultValues(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema as any).properties ?? {}
  const result: Record<string, unknown> = {}
  for (const [key, prop] of Object.entries(props as Record<string, any>)) {
    if (prop.default !== undefined) result[key] = prop.default
    else if (prop.type === 'array') result[key] = []
  }
  return result
}

function validateRequired(schema: Record<string, unknown>, values: Record<string, unknown>): Record<string, string> {
  const required: string[] = (schema as any).required ?? []
  const errors: Record<string, string> = {}
  for (const key of required) {
    const v = values[key]
    if (v === undefined || v === null || v === '') errors[key] = 'Required'
  }
  return errors
}

const STATUS_ICON: Record<LogEntry['status'], string> = {
  added: '✓',
  updated: '↑',
  unchanged: '·',
}
const STATUS_COLOR: Record<LogEntry['status'], string> = {
  added: '#2e7d32',
  updated: '#6b7de0',
  unchanged: '#aaa',
}

export default function PluginIngestDialog({ projectId, onClose, onSuccess }: Props) {
  const [selectedPlugin, setSelectedPlugin] = useState<string | null>(null)
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<LogEntry[]>([])
  const [counts, setCounts] = useState({ added: 0, updated: 0, skipped: 0 })
  const [done, setDone] = useState(false)
  const [ingestError, setIngestError] = useState<string | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  const { data: plugins, isLoading: pluginsLoading } = useQuery({
    queryKey: ['plugins'],
    queryFn: () => api.plugins.list(),
  })

  const { data: savedConfig } = useQuery({
    queryKey: ['plugin-config', projectId],
    queryFn: () => api.works.getPluginConfig(projectId),
  })

  useEffect(() => {
    if (!plugins?.length) return
    if (!selectedPlugin) {
      const initial = savedConfig?.plugin_name ?? plugins[0]?.name ?? null
      setSelectedPlugin(initial)
    }
  }, [plugins, savedConfig, selectedPlugin])

  useEffect(() => {
    if (!plugins || !selectedPlugin) return
    const plugin = plugins.find(p => p.name === selectedPlugin)
    if (!plugin) return
    const defaults = defaultValues(plugin.config_schema)
    if (savedConfig?.plugin_name === selectedPlugin) {
      setConfigValues({ ...defaults, ...savedConfig.config })
    } else {
      setConfigValues(defaults)
    }
    setErrors({})
  }, [selectedPlugin, savedConfig, plugins])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [log])

  const handleSubmit = async () => {
    const plugin = plugins?.find(p => p.name === selectedPlugin)
    if (!plugin) return
    const errs = validateRequired(plugin.config_schema, configValues)
    if (Object.keys(errs).length > 0) { setErrors(errs); return }
    setErrors({})
    setRunning(true)
    setLog([])
    setCounts({ added: 0, updated: 0, skipped: 0 })
    setDone(false)
    setIngestError(null)

    try {
      await api.works.ingestPluginStream(projectId, selectedPlugin!, configValues, (event: PluginIngestEvent) => {
        if ('error' in event) {
          setIngestError(event.error)
          setRunning(false)
          return
        }
        if ('complete' in event) {
          setCounts({ added: event.added, updated: event.updated, skipped: event.skipped })
          setDone(true)
          setRunning(false)
          onSuccess({ added: event.added, updated: event.updated, skipped: event.skipped })
          return
        }
        if ('work' in event) {
          setLog(prev => [...prev, { work: event.work, status: event.status }])
          setCounts({ added: event.added, updated: event.updated, skipped: event.skipped })
        }
      })
    } catch (e) {
      setIngestError(e instanceof Error ? e.message : String(e))
      setRunning(false)
    }
  }

  const selectedPluginInfo = plugins?.find(p => p.name === selectedPlugin)

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget && !running) onClose() }}
    >
      <div style={{
        background: '#fff', color: '#1a1a1a', borderRadius: 10, width: 580, maxHeight: '88vh',
        display: 'flex', flexDirection: 'column', boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Plugin Ingest</h3>
          {!running && <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#888' }}>×</button>}
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {pluginsLoading && <p style={{ color: '#888' }}>Loading plugins…</p>}

          {plugins && plugins.length > 0 && !running && !done && (
            <>
              {/* Plugin selector */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 13, fontWeight: 500, marginBottom: 6, display: 'block' }}>Plugin</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {plugins.map(p => (
                    <button key={p.name} type="button" onClick={() => setSelectedPlugin(p.name)} style={{
                      padding: '6px 14px', borderRadius: 4, border: '1px solid',
                      borderColor: selectedPlugin === p.name ? '#6b7de0' : '#ddd',
                      background: selectedPlugin === p.name ? '#6b7de0' : 'transparent',
                      color: selectedPlugin === p.name ? '#fff' : '#333',
                      cursor: 'pointer', fontSize: 13,
                    }}>
                      {p.title || p.name}
                    </button>
                  ))}
                </div>
                {selectedPluginInfo?.description && (
                  <p style={{ margin: '6px 0 0', fontSize: 12, color: '#888' }}>{selectedPluginInfo.description}</p>
                )}
              </div>

              {selectedPluginInfo && (
                <PluginConfigEditor
                  schema={selectedPluginInfo.config_schema as any}
                  value={configValues}
                  onChange={setConfigValues}
                  errors={errors}
                />
              )}
            </>
          )}

          {/* Progress log */}
          {(running || done || ingestError) && (
            <div>
              {/* Running stats bar */}
              <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 13 }}>
                <span style={{ color: '#2e7d32' }}>✓ {counts.added} added</span>
                <span style={{ color: '#6b7de0' }}>↑ {counts.updated} updated</span>
                <span style={{ color: '#aaa' }}>· {counts.skipped} unchanged</span>
                {running && <span style={{ color: '#888', marginLeft: 'auto' }}>fetching…</span>}
              </div>

              {/* Scrollable work log */}
              <div style={{
                background: '#f8f8f8', border: '1px solid #e0e0e0', borderRadius: 6,
                padding: '8px 12px', maxHeight: 260, overflowY: 'auto',
                fontFamily: 'monospace', fontSize: 12, lineHeight: 1.6,
              }}>
                {log.length === 0 && running && (
                  <span style={{ color: '#aaa' }}>Connecting to {selectedPlugin}…</span>
                )}
                {log.map((entry, i) => (
                  <div key={i} style={{ color: STATUS_COLOR[entry.status] }}>
                    {STATUS_ICON[entry.status]} {entry.work}
                  </div>
                ))}
                {done && (
                  <div style={{ color: '#2e7d32', marginTop: 4 }}>
                    ✓ Complete — {counts.added} added, {counts.updated} updated, {counts.skipped} unchanged
                  </div>
                )}
                <div ref={logEndRef} />
              </div>

              {ingestError && (
                <div style={{ marginTop: 10, padding: '8px 12px', background: '#fff5f5', border: '1px solid #fca5a5', borderRadius: 4, fontSize: 13, color: '#c00' }}>
                  {ingestError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid #e0e0e0', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          {!running && (
            <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer' }}>
              {done || ingestError ? 'Close' : 'Cancel'}
            </button>
          )}
          {!running && !done && !ingestError && (
            <button
              onClick={handleSubmit}
              disabled={!selectedPlugin}
              style={{
                padding: '6px 16px', background: selectedPlugin ? '#6b7de0' : '#ccc',
                color: '#fff', border: 'none', borderRadius: 4,
                cursor: selectedPlugin ? 'pointer' : 'default',
              }}
            >
              Save &amp; Ingest
            </button>
          )}
          {running && (
            <span style={{ fontSize: 13, color: '#888', alignSelf: 'center' }}>
              Ingesting… please wait
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

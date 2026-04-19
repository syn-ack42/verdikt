import { useEffect, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import type { IngestResult, PluginInfo } from '../api/types'
import PluginConfigEditor from './PluginConfigEditor'

interface Props {
  projectId: string
  onClose: () => void
  onSuccess: (result: IngestResult) => void
}

function defaultValues(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema as any).properties ?? {}
  const result: Record<string, unknown> = {}
  for (const [key, prop] of Object.entries(props as Record<string, any>)) {
    if (prop.default !== undefined) {
      result[key] = prop.default
    } else if (prop.type === 'array') {
      result[key] = []
    }
  }
  return result
}

function validateRequired(schema: Record<string, unknown>, values: Record<string, unknown>): Record<string, string> {
  const required: string[] = (schema as any).required ?? []
  const errors: Record<string, string> = {}
  for (const key of required) {
    const v = values[key]
    if (v === undefined || v === null || v === '') {
      errors[key] = 'Required'
    }
  }
  return errors
}

export default function PluginIngestDialog({ projectId, onClose, onSuccess }: Props) {
  const [selectedPlugin, setSelectedPlugin] = useState<string | null>(null)
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [result, setResult] = useState<IngestResult | null>(null)

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
    setResult(null)
  }, [selectedPlugin, savedConfig, plugins])

  const ingest = useMutation({
    mutationFn: () => api.works.ingestPlugin(projectId, selectedPlugin!, configValues),
    onSuccess: (r) => {
      setResult(r)
      onSuccess(r)
    },
  })

  const handleSubmit = () => {
    const plugin = plugins?.find(p => p.name === selectedPlugin)
    if (!plugin) return
    const errs = validateRequired(plugin.config_schema, configValues)
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }
    setErrors({})
    ingest.mutate()
  }

  const selectedPluginInfo = plugins?.find(p => p.name === selectedPlugin)

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#fff', color: '#1a1a1a', borderRadius: 10, width: 560, maxHeight: '85vh',
        display: 'flex', flexDirection: 'column', boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e0e0e0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Plugin Ingest</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#888' }}>×</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {pluginsLoading && <p style={{ color: '#888' }}>Loading plugins…</p>}

          {plugins && plugins.length > 0 && (
            <>
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 13, fontWeight: 500, marginBottom: 6, display: 'block' }}>Plugin</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {plugins.map(p => (
                    <button
                      key={p.name}
                      type="button"
                      onClick={() => setSelectedPlugin(p.name)}
                      style={{
                        padding: '6px 14px',
                        borderRadius: 4,
                        border: '1px solid',
                        borderColor: selectedPlugin === p.name ? '#6b7de0' : '#ddd',
                        background: selectedPlugin === p.name ? '#6b7de0' : 'transparent',
                        color: selectedPlugin === p.name ? '#fff' : '#333',
                        cursor: 'pointer',
                        fontSize: 13,
                      }}
                    >
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

          {ingest.error && (
            <p style={{ marginTop: 12, fontSize: 13, color: '#c00' }}>
              {(ingest.error as any)?.message ?? String(ingest.error)}
            </p>
          )}

          {result && (
            <div style={{ marginTop: 12, padding: '8px 12px', background: '#e8f5e9', borderRadius: 4, fontSize: 13, color: '#2e7d32' }}>
              Done — added {result.added}, updated {result.updated}, unchanged {result.skipped}
            </div>
          )}
        </div>

        <div style={{ padding: '12px 20px', borderTop: '1px solid #e0e0e0', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer' }}>
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              onClick={handleSubmit}
              disabled={!selectedPlugin || ingest.isPending}
              style={{
                padding: '6px 16px',
                background: selectedPlugin ? '#6b7de0' : '#ccc',
                color: '#fff', border: 'none', borderRadius: 4,
                cursor: selectedPlugin ? 'pointer' : 'default',
              }}
            >
              {ingest.isPending ? 'Ingesting…' : 'Save & Ingest'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

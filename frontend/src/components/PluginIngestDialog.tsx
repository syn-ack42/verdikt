import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { PluginAction, PluginInfo } from '../api/types'
import PluginConfigEditor from './PluginConfigEditor'
import StoragePicker, { type Selection } from './StoragePicker'
import PluginActionModal from './PluginActionModal'

interface Props {
  projectId: string
  domain: string
  onClose: () => void
  onIngest: (pluginName: string, config: Record<string, unknown>) => void
  onBatchIngest?: (pluginName: string) => void
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

export default function PluginIngestDialog({ projectId, domain, onClose, onIngest, onBatchIngest }: Props) {
  const [selectedPlugin, setSelectedPlugin] = useState<string | null>(null)
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [activeAction, setActiveAction] = useState<PluginAction | null>(null)

  const { data: plugins, isLoading: pluginsLoading } = useQuery({
    queryKey: ['plugins', domain],
    queryFn: () => api.plugins.list(domain),
  })

  const { data: savedConfigs } = useQuery({
    queryKey: ['plugin-config', projectId],
    queryFn: () => api.works.getPluginConfig(projectId),
  })

  useEffect(() => {
    if (!plugins?.length) return
    if (!selectedPlugin) {
      const firstSavedPlugin = savedConfigs && Object.keys(savedConfigs)[0]
      setSelectedPlugin(firstSavedPlugin ?? plugins[0]?.name ?? null)
    }
  }, [plugins, savedConfigs, selectedPlugin])

  useEffect(() => {
    if (!plugins || !selectedPlugin) return
    const plugin = plugins.find(p => p.name === selectedPlugin)
    if (!plugin) return
    const defaults = defaultValues(plugin.config_schema)
    const saved = savedConfigs?.[selectedPlugin]
    if (saved) {
      setConfigValues({ ...defaults, ...saved.config })
    } else {
      setConfigValues(defaults)
    }
    setErrors({})
  }, [selectedPlugin, savedConfigs, plugins])

  const handleSubmit = async () => {
    const plugin = plugins?.find(p => p.name === selectedPlugin)
    if (!plugin) return
    const errs = validateRequired(plugin.config_schema, configValues)
    if (selectedPlugin === 'storage') {
      const sels = (configValues.selections as Selection[] | undefined) ?? []
      if (sels.length === 0) { setErrors({ selections: 'Select at least one file or folder' }); return }
    }
    if (Object.keys(errs).length > 0) { setErrors(errs); return }
    if (plugin.supports_batched_ingest && onBatchIngest) {
      await api.works.savePluginConfig(projectId, selectedPlugin!, configValues)
      onBatchIngest(selectedPlugin!)
    } else {
      onIngest(selectedPlugin!, configValues)
    }
    onClose()
  }

  const selectedPluginInfo = plugins?.find((p: PluginInfo) => p.name === selectedPlugin)
  const isBatch = !!(selectedPluginInfo?.supports_batched_ingest && onBatchIngest)
  const buttonLabel = selectedPluginInfo
    ? `${isBatch ? 'Start' : 'Ingest'} ${selectedPluginInfo.title || selectedPlugin}`
    : 'Ingest'
  const pluginActions = selectedPluginInfo?.actions ?? []

  return (
    <>
    {activeAction && selectedPlugin && (
      <PluginActionModal
        projectId={projectId}
        pluginName={selectedPlugin}
        action={activeAction}
        onClose={() => setActiveAction(null)}
      />
    )}
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--bg, #fff)', color: 'var(--text, #1a1a1a)', borderRadius: 10, width: 'min(580px, 94vw)', maxHeight: '88vh',
        display: 'flex', flexDirection: 'column', boxShadow: '0 8px 32px rgba(0,0,0,0.2)', overflow: 'hidden',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border, #e0e0e0)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>Ingest</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#888' }}>×</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {pluginsLoading && <p style={{ color: '#888' }}>Loading plugins…</p>}

          {plugins && plugins.length > 0 && (
            <>
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 13, fontWeight: 500, marginBottom: 6, display: 'block' }}>Source</label>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {plugins.map((p: PluginInfo) => (
                    <button key={p.name} type="button" onClick={() => setSelectedPlugin(p.name)} style={{
                      padding: '6px 14px', borderRadius: 4, border: '1px solid',
                      borderColor: selectedPlugin === p.name ? '#6b7de0' : 'var(--border, #ddd)',
                      background: selectedPlugin === p.name ? '#6b7de0' : 'transparent',
                      color: selectedPlugin === p.name ? '#fff' : 'var(--text, #333)',
                      cursor: 'pointer', fontSize: 13,
                    }}>
                      {p.title || p.name}
                    </button>
                  ))}
                </div>
                {selectedPluginInfo?.description && (
                  <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--text-muted, #888)' }}>{selectedPluginInfo.description}</p>
                )}
              </div>

              {selectedPluginInfo && selectedPlugin === 'storage' ? (
                <div>
                  <label style={{ fontSize: 13, fontWeight: 500, marginBottom: 6, display: 'block' }}>
                    Select files and folders
                  </label>
                  <StoragePicker
                    value={(configValues.selections as Selection[]) ?? []}
                    onChange={selections => setConfigValues(v => ({ ...v, selections }))}
                  />
                  {errors.selections && (
                    <div style={{ fontSize: 12, color: '#c00', marginTop: 4 }}>{errors.selections}</div>
                  )}
                </div>
              ) : selectedPluginInfo ? (
                <PluginConfigEditor
                  schema={selectedPluginInfo.config_schema as any}
                  value={configValues}
                  onChange={setConfigValues}
                  errors={errors}
                />
              ) : null}
            </>
          )}
        </div>

        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border, #e0e0e0)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {pluginActions.map(action => (
              <button
                key={action.name}
                type="button"
                onClick={() => setActiveAction(action)}
                title={action.description}
                style={{
                  padding: '6px 14px', border: '1px solid var(--border, #ddd)', borderRadius: 4,
                  cursor: 'pointer', background: 'transparent', color: 'var(--text, #333)', fontSize: 13,
                }}
              >
                {action.title}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid var(--border, #ddd)', borderRadius: 4, cursor: 'pointer', background: 'transparent', color: 'var(--text, #333)' }}>
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!selectedPlugin}
              style={{
                padding: '6px 16px', background: selectedPlugin ? '#6b7de0' : '#ccc',
                color: '#fff', border: 'none', borderRadius: 4,
                cursor: selectedPlugin ? 'pointer' : 'default',
              }}
            >
              {buttonLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
    </>
  )
}

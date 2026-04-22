interface JsonSchemaProperty {
  type?: string | string[]
  title?: string
  description?: string
  format?: string
  default?: unknown
  minimum?: number
  maximum?: number
  items?: { type?: string; format?: string }
}

interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>
  required?: string[]
}

interface Props {
  schema: JsonSchema
  value: Record<string, unknown>
  onChange: (updated: Record<string, unknown>) => void
  errors?: Record<string, string>
}

function ArrayField({
  prop, value, onChange,
}: { prop: JsonSchemaProperty; value: unknown; onChange: (v: unknown) => void }) {
  const items = Array.isArray(value) ? (value as string[]) : []
  const set = (idx: number, v: string) => {
    const next = [...items]
    next[idx] = v
    onChange(next)
  }
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx))
  const add = () => onChange([...items, ''])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {items.map((item, i) => (
        <div key={i} style={{ display: 'flex', gap: 4 }}>
          <input
            type={prop.items?.format === 'uri' ? 'url' : 'text'}
            value={item}
            onChange={e => set(i, e.target.value)}
            placeholder={prop.description ?? prop.title ?? ''}
            style={{ flex: 1, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--text)' }}
          />
          <button type="button" onClick={() => remove(i)} style={{ color: '#c00', border: 'none', background: 'none', cursor: 'pointer' }}>×</button>
        </div>
      ))}
      <button type="button" onClick={add} style={{ alignSelf: 'flex-start', fontSize: 12, color: '#6b7de0', border: 'none', background: 'none', cursor: 'pointer' }}>
        + Add URL
      </button>
    </div>
  )
}

export default function PluginConfigEditor({ schema, value, onChange, errors }: Props) {
  const properties = schema.properties ?? {}
  const required = new Set(schema.required ?? [])

  const update = (key: string, v: unknown) => onChange({ ...value, [key]: v })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Object.entries(properties).map(([key, prop]) => {
        const label = prop.title ?? key
        const isRequired = required.has(key)
        const currentVal = value[key] ?? prop.default ?? ''
        const error = errors?.[key]
        const type = Array.isArray(prop.type) ? prop.type[0] : prop.type

        return (
          <div key={key}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
              {label}{isRequired && <span style={{ color: '#c00' }}> *</span>}
            </label>
            {prop.description && (
              <p style={{ margin: '0 0 4px', fontSize: 12, color: 'var(--text-muted)' }}>{prop.description}</p>
            )}
            {type === 'array' ? (
              <ArrayField prop={prop} value={currentVal} onChange={v => update(key, v)} />
            ) : (
              <input
                type={
                  prop.format === 'password' ? 'password'
                  : prop.format === 'uri' ? 'url'
                  : type === 'integer' || type === 'number' ? 'number'
                  : 'text'
                }
                value={String(currentVal)}
                min={prop.minimum}
                max={prop.maximum}
                onChange={e => {
                  const v = (type === 'integer' || type === 'number')
                    ? (e.target.value === '' ? '' : Number(e.target.value))
                    : e.target.value
                  update(key, v)
                }}
                placeholder={prop.description ?? ''}
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  border: `1px solid ${error ? '#f59e0b' : 'var(--border)'}`,
                  borderRadius: 4,
                  boxSizing: 'border-box',
                  background: 'var(--bg)',
                  color: 'var(--text)',
                }}
              />
            )}
            {error && <p style={{ margin: '2px 0 0', fontSize: 11, color: '#b45309' }}>{error}</p>}
          </div>
        )
      })}
    </div>
  )
}

interface JsonSchemaPropertyDef {
  type?: string
  format?: string
  title?: string
  description?: string
  minimum?: number
  maximum?: number
  default?: unknown
  enum?: string[]
}

interface JsonSchemaProperty {
  type?: string | string[]
  title?: string
  description?: string
  format?: string
  default?: unknown
  minimum?: number
  maximum?: number
  enum?: string[]
  items?: {
    type?: string
    format?: string
    properties?: Record<string, JsonSchemaPropertyDef>
  }
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

const inputStyle: React.CSSProperties = {
  padding: '4px 8px',
  border: '1px solid var(--border)',
  borderRadius: 4,
  background: 'var(--bg)',
  color: 'var(--text)',
}

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: 'pointer',
}

// Return the "for type=X" constraint from a description string, or null.
function showWhenType(description?: string): string | null {
  const m = description?.match(/\(for type=(\w+)\)/i)
  return m ? m[1] : null
}

// Array of plain strings/URLs
function StringArrayField({
  prop, value, onChange,
}: { prop: JsonSchemaProperty; value: unknown; onChange: (v: unknown) => void }) {
  const items = Array.isArray(value) ? (value as string[]) : []
  const set = (idx: number, v: string) => { const next = [...items]; next[idx] = v; onChange(next) }
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
            style={{ flex: 1, ...inputStyle }}
          />
          <button type="button" onClick={() => remove(i)} style={{ color: '#c00', border: 'none', background: 'none', cursor: 'pointer' }}>×</button>
        </div>
      ))}
      <button type="button" onClick={add} style={{ alignSelf: 'flex-start', fontSize: 12, color: '#6b7de0', border: 'none', background: 'none', cursor: 'pointer' }}>
        + Add
      </button>
    </div>
  )
}

// Array of objects — each property gets a visible label, enum fields become <select>,
// and fields with "(for type=X)" in their description are conditionally shown.
function ObjectArrayField({
  prop, value, onChange,
}: { prop: JsonSchemaProperty; value: unknown; onChange: (v: unknown) => void }) {
  const items = Array.isArray(value) ? (value as Record<string, unknown>[]) : []
  const properties = prop.items!.properties!

  // Field with enum = discriminator (e.g. "type")
  const discriminatorKey = Object.keys(properties).find(k => (properties[k].enum?.length ?? 0) > 0) ?? null

  const set = (idx: number, key: string, v: unknown) => {
    onChange(items.map((item, i) => i === idx ? { ...item, [key]: v } : item))
  }
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx))

  const add = () => {
    const prev = items[items.length - 1]
    const newItem: Record<string, unknown> = {}
    for (const [key, schema] of Object.entries(properties)) {
      if (schema.format === 'uri') {
        newItem[key] = ''
      } else if (schema.enum) {
        newItem[key] = prev?.[key] ?? schema.default ?? schema.enum[0] ?? ''
      } else {
        newItem[key] = prev?.[key] ?? schema.default ?? (schema.type === 'integer' || schema.type === 'number' ? 0 : '')
      }
    }
    onChange([...items, newItem])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((item, i) => {
        const discriminatorValue = discriminatorKey ? String(item[discriminatorKey] ?? '') : null

        // Hide fields whose description specifies a type constraint that doesn't match
        const visible = Object.entries(properties).filter(([, schema]) => {
          const constraint = showWhenType(schema.description)
          return !constraint || discriminatorValue === constraint
        })

        return (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-end', flexWrap: 'wrap', padding: '8px 10px', background: 'var(--surface, rgba(128,128,128,0.04))', borderRadius: 6, border: '1px solid var(--border)' }}>
            {visible.map(([key, schema]) => {
              const isEnum = (schema.enum?.length ?? 0) > 0
              const isNum = schema.type === 'integer' || schema.type === 'number'
              const currentVal = item[key] ?? schema.default ?? (isEnum ? schema.enum![0] : '')

              return (
                <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: (!isEnum && !isNum) ? 1 : undefined, minWidth: isNum ? 80 : undefined }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', userSelect: 'none' }}>
                    {schema.title ?? key}
                  </span>
                  {isEnum ? (
                    <select
                      value={String(currentVal)}
                      onChange={e => set(i, key, e.target.value)}
                      style={{ ...selectStyle, minWidth: 100 }}
                    >
                      {schema.enum!.map(opt => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={isNum ? 'number' : 'text'}
                      value={String(currentVal)}
                      min={schema.minimum}
                      max={schema.maximum}
                      onChange={e => {
                        const v = isNum ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value
                        set(i, key, v)
                      }}
                      style={{ ...inputStyle, width: isNum ? 80 : undefined }}
                    />
                  )}
                </div>
              )
            })}
            <button type="button" onClick={() => remove(i)} style={{ color: '#c00', border: 'none', background: 'none', cursor: 'pointer', paddingBottom: 3, flexShrink: 0 }}>×</button>
          </div>
        )
      })}
      <button type="button" onClick={add} style={{ alignSelf: 'flex-start', fontSize: 12, color: '#6b7de0', border: 'none', background: 'none', cursor: 'pointer' }}>
        + Add source
      </button>
    </div>
  )
}

function ArrayField({
  prop, value, onChange,
}: { prop: JsonSchemaProperty; value: unknown; onChange: (v: unknown) => void }) {
  if (prop.items?.type === 'object' && prop.items?.properties) {
    return <ObjectArrayField prop={prop} value={value} onChange={onChange} />
  }
  return <StringArrayField prop={prop} value={value} onChange={onChange} />
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
        const isEnum = (prop.enum?.length ?? 0) > 0

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
            ) : isEnum ? (
              <select
                value={String(currentVal)}
                onChange={e => update(key, e.target.value)}
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  border: `1px solid ${error ? '#f59e0b' : 'var(--border)'}`,
                  borderRadius: 4,
                  boxSizing: 'border-box',
                  background: 'var(--bg)',
                  color: 'var(--text)',
                  cursor: 'pointer',
                }}
              >
                {prop.enum!.map(opt => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
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

import { useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { SiteSettings, User } from '../api/types'

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</label>
      {children}
      {help && <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '3px 0 0' }}>{help}</p>}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '7px 10px', borderRadius: 4, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box',
}

export default function AdminSettings() {
  const { user: me } = useOutletContext<{ user: User }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [smtpTestResult, setSmtpTestResult] = useState<string | null>(null)

  if (!me.is_admin) return <div style={{ padding: 24 }}>Access denied.</div>

  const { data: settings, isLoading } = useQuery({
    queryKey: ['admin-settings'],
    queryFn: () => api.admin.getSettings(),
  })

  const [form, setForm] = useState<Partial<SiteSettings>>({})
  const merged = { ...settings, ...form } as SiteSettings

  const f = (key: keyof SiteSettings) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(p => ({ ...p, [key]: e.target.value }))

  const save = useMutation({
    mutationFn: () => api.admin.updateSettings(merged),
    onSuccess: (data) => {
      qc.setQueryData(['admin-settings'], data)
      setForm({})
    },
  })

  const testSmtp = useMutation({
    mutationFn: () => api.admin.testSmtp(),
    onSuccess: () => setSmtpTestResult('Test email sent successfully.'),
    onError: (err: any) => setSmtpTestResult(`Failed: ${err.message}`),
  })

  if (isLoading) return <p style={{ padding: 24, color: 'var(--text-muted)' }}>Loading…</p>

  const isDirty = Object.keys(form).length > 0

  return (
    <div style={{ maxWidth: 600, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <button onClick={() => navigate('/')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0 }}>
          ← Projects
        </button>
        <h2 style={{ margin: 0, flex: 1 }}>Site Settings</h2>
        <button onClick={() => navigate('/admin/users')} style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>
          Users
        </button>
      </div>

      {/* Default limits */}
      <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 20, marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15 }}>Default limits</h3>
        <Field label="Default storage limit (MB)" help="Per-user limit for file uploads. 0 = unlimited. Individual users can be given higher limits.">
          <input type="number" min={0} value={merged.default_storage_limit_mb ?? '10'} onChange={f('default_storage_limit_mb')} style={inputStyle} />
        </Field>
        <Field label="Default daily token grant" help="Tokens issued to each user per day. Leave blank for unlimited.">
          <input type="number" min={0} value={merged.default_daily_token_grant ?? ''} placeholder="unlimited" onChange={f('default_daily_token_grant')} style={inputStyle} />
        </Field>
        <Field label="Token grant expiry (days)" help="How long issued daily grants remain valid.">
          <input type="number" min={1} value={merged.default_token_grant_expiry_days ?? '7'} onChange={f('default_token_grant_expiry_days')} style={inputStyle} />
        </Field>
      </section>

      {/* SMTP */}
      <section style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 20, marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 4px', fontSize: 15 }}>SMTP (email)</h3>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 16px' }}>
          Required for email confirmation on registration. Env vars (VERDIKT_SMTP_*) are used as fallback when these fields are empty.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px', gap: 10 }}>
          <Field label="Host">
            <input type="text" value={merged.smtp_host ?? ''} onChange={f('smtp_host')} placeholder="smtp.example.com" style={inputStyle} />
          </Field>
          <Field label="Port">
            <input type="number" value={merged.smtp_port ?? '587'} onChange={f('smtp_port')} style={inputStyle} />
          </Field>
        </div>
        <Field label="Username">
          <input type="text" value={merged.smtp_user ?? ''} onChange={f('smtp_user')} placeholder="user@example.com" style={inputStyle} />
        </Field>
        <Field label="Password">
          <input type="password" value={merged.smtp_password ?? ''} onChange={f('smtp_password')} placeholder="(unchanged)" style={inputStyle} />
        </Field>
        <Field label="From address">
          <input type="email" value={merged.smtp_from ?? ''} onChange={f('smtp_from')} placeholder="verdikt@example.com" style={inputStyle} />
        </Field>
        <Field label="Security">
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={(merged.smtp_use_tls ?? 'true') === 'true'}
              onChange={e => setForm(p => ({ ...p, smtp_use_tls: e.target.checked ? 'true' : 'false' }))}
            />
            Use STARTTLS (port 587). Uncheck for implicit TLS (port 465).
          </label>
        </Field>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
          <button
            onClick={() => { save.mutate(); setSmtpTestResult(null) }}
            disabled={save.isPending || !isDirty}
            style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', cursor: 'pointer', background: 'none' }}
          >
            Save first, then test
          </button>
          <button
            onClick={() => { setSmtpTestResult(null); testSmtp.mutate() }}
            disabled={testSmtp.isPending || isDirty}
            style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', cursor: 'pointer', background: 'none' }}
          >
            {testSmtp.isPending ? 'Sending…' : 'Send test email'}
          </button>
          {smtpTestResult && (
            <span style={{ fontSize: 12, color: smtpTestResult.startsWith('Failed') ? '#c00' : '#2e7d32' }}>
              {smtpTestResult}
            </span>
          )}
        </div>
      </section>

      {save.isError && <p style={{ color: '#c00', fontSize: 13 }}>{(save.error as Error).message}</p>}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending || !isDirty}
          style={{ padding: '8px 20px', borderRadius: 4, border: 'none', background: isDirty ? '#6b7de0' : 'var(--border)', color: isDirty ? '#fff' : 'var(--text-muted)', fontSize: 14, cursor: isDirty ? 'pointer' : 'default' }}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        {isDirty && (
          <button onClick={() => setForm({})} style={{ padding: '8px 16px', borderRadius: 4, fontSize: 14 }}>
            Cancel
          </button>
        )}
        {save.isSuccess && !isDirty && <span style={{ fontSize: 13, color: '#2e7d32', alignSelf: 'center' }}>Saved.</span>}
      </div>
    </div>
  )
}

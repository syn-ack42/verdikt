import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api } from '../api/client'
import PasswordStrengthMeter, { scorePassword } from '../components/PasswordStrengthMeter'

export default function Register() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pendingEmail, setPendingEmail] = useState<string | null>(null)

  const { score } = scorePassword(password)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== confirm) { setError('Passwords do not match'); return }
    if (score < 3) { setError('Please choose a stronger password (score needs to be Strong or better)'); return }
    setLoading(true)
    try {
      const res = await api.auth.register(email, password)
      if (res.pending_confirmation) {
        setPendingEmail(email)
      } else {
        navigate('/')
      }
    } catch (err: any) {
      setError(err.message ?? 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  if (pendingEmail) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ width: '100%', maxWidth: 360, textAlign: 'center' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>✉</div>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Check your inbox</h1>
          <p style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 8 }}>
            A confirmation link has been sent to <strong>{pendingEmail}</strong>.
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 24 }}>
            Click the link in the email to activate your account. The link expires in 48 hours.
          </p>
          <Link to="/login" style={{ color: '#6b7de0', fontSize: 14 }}>Back to sign in</Link>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 380 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Create account</h1>

        <div style={{ background: 'rgba(192,0,0,0.06)', border: '1px solid rgba(192,0,0,0.2)', borderRadius: 6, padding: '10px 14px', marginBottom: 20 }}>
          <p style={{ fontSize: 13, margin: 0 }}>
            <strong>Your data is encrypted with your password.</strong> If you lose it, your ratings and profiles cannot be recovered —
            there is no password reset. Only store data you have backed up elsewhere, or export your profiles regularly.
          </p>
        </div>

        {error && (
          <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
            <span style={{ fontSize: 13, color: '#c00' }}>{error}</span>
          </div>
        )}

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>Email</label>
            <input
              type="email" value={email} onChange={e => setEmail(e.target.value)}
              required autoFocus
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>Password</label>
            <input
              type="password" value={password} onChange={e => setPassword(e.target.value)} required
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
            <PasswordStrengthMeter password={password} />
            <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '4px 0 0' }}>
              Tip: a passphrase of three or more random words is both strong and memorable.
            </p>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>Confirm password</label>
            <input
              type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
            {confirm && password !== confirm && (
              <p style={{ fontSize: 11, color: '#c00', margin: '3px 0 0' }}>Passwords do not match</p>
            )}
          </div>
          <button
            type="submit"
            disabled={loading || score < 3 || (!!confirm && password !== confirm)}
            style={{
              padding: '9px 0', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 4, fontSize: 14,
              cursor: loading ? 'default' : 'pointer', marginTop: 4,
              opacity: score < 3 || (!!confirm && password !== confirm) ? 0.6 : 1,
            }}
          >
            {loading ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p style={{ marginTop: 20, fontSize: 13, color: 'var(--text-muted)', textAlign: 'center' }}>
          Already have an account?{' '}
          <Link to="/login" style={{ color: '#6b7de0' }}>Sign in</Link>
        </p>
      </div>
    </div>
  )
}

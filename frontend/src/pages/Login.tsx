import { useState, useEffect } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'

const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  github: 'GitHub',
}

export default function Login() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [oauthProviders, setOauthProviders] = useState<string[]>([])

  useEffect(() => {
    api.auth.oauthProviders().then(setOauthProviders).catch(() => {})
    const oauthError = searchParams.get('error')
    if (oauthError) {
      const messages: Record<string, string> = {
        oauth_denied: 'Sign-in was cancelled.',
        oauth_token_failed: 'Could not exchange OAuth token. Try again.',
        oauth_userinfo_failed: 'Could not retrieve account information.',
        oauth_no_email: 'No email address found in your account.',
        oauth_no_id: 'Could not identify your account.',
        account_blocked: 'Your account has been blocked.',
      }
      setError(messages[oauthError] ?? 'OAuth sign-in failed.')
    }
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await api.auth.login(email, password)
      navigate('/')
    } catch (err: any) {
      setError(err.message ?? 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 360 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Sign in to Verdikt</h1>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 24 }}>
          Your preference data is encrypted with your password.
        </p>

        {error && (
          <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
            <span style={{ fontSize: 13, color: '#c00' }}>{error}</span>
          </div>
        )}

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoFocus
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            style={{ padding: '9px 0', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 4, fontSize: 14, cursor: loading ? 'default' : 'pointer', marginTop: 4 }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {oauthProviders.length > 0 && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '20px 0 16px' }}>
              <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>or</span>
              <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {oauthProviders.map(provider => (
                <a
                  key={provider}
                  href={api.auth.oauthAuthorizeUrl(provider)}
                  style={{
                    display: 'block', textAlign: 'center', padding: '9px 0',
                    border: '1px solid var(--border)', borderRadius: 4, fontSize: 14,
                    color: 'var(--text)', textDecoration: 'none', cursor: 'pointer',
                  }}
                >
                  Sign in with {PROVIDER_LABELS[provider] ?? provider}
                </a>
              ))}
            </div>
          </>
        )}

        <p style={{ marginTop: 20, fontSize: 13, color: 'var(--text-muted)', textAlign: 'center' }}>
          No account?{' '}
          <Link to="/register" style={{ color: '#6b7de0' }}>Create one</Link>
        </p>
      </div>
    </div>
  )
}

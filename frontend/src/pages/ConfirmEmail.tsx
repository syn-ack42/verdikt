import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { api } from '../api/client'

export default function ConfirmEmail() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const [state, setState] = useState<'pending' | 'ok' | 'error'>('pending')
  const [email, setEmail] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const [resendEmail, setResendEmail] = useState('')
  const [resendState, setResendState] = useState<'idle' | 'sending' | 'sent'>('idle')

  useEffect(() => {
    if (!token) { setState('error'); setErrorMsg('No confirmation token in URL.'); return }
    api.auth.confirmEmail(token)
      .then(res => { setEmail(res.email); setState('ok') })
      .catch(err => { setErrorMsg(err.message ?? 'Confirmation failed'); setState('error') })
  }, [token])

  function handleResend() {
    if (!resendEmail.trim()) return
    setResendState('sending')
    api.auth.resendConfirmation(resendEmail.trim())
      .then(() => setResendState('sent'))
      .catch(() => setResendState('sent'))
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 360, textAlign: 'center' }}>
        {state === 'pending' && <p style={{ color: 'var(--text-muted)' }}>Confirming…</p>}

        {state === 'ok' && (
          <>
            <div style={{ fontSize: 48, marginBottom: 16 }}>✓</div>
            <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Email confirmed</h1>
            <p style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 24 }}>
              {email} is confirmed. Your account is active.
            </p>
            <Link to="/login">
              <button style={{ padding: '9px 24px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 4, fontSize: 14, cursor: 'pointer' }}>
                Sign in
              </button>
            </Link>
          </>
        )}

        {state === 'error' && (
          <>
            <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Confirmation failed</h1>
            <p style={{ fontSize: 14, color: '#c00', marginBottom: 24 }}>{errorMsg}</p>

            {resendState === 'sent' ? (
              <p style={{ fontSize: 14, color: 'var(--text-muted)' }}>
                If that address is registered and unconfirmed, a new link is on its way.
              </p>
            ) : (
              <div style={{ textAlign: 'left' }}>
                <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 10 }}>
                  Resend a confirmation link:
                </p>
                <input
                  type="email"
                  placeholder="your@email.com"
                  value={resendEmail}
                  onChange={e => setResendEmail(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleResend()}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 4, fontSize: 14, marginBottom: 8 }}
                />
                <button
                  onClick={handleResend}
                  disabled={resendState === 'sending'}
                  style={{ width: '100%', padding: '9px', background: '#6b7de0', color: '#fff', border: 'none', borderRadius: 4, fontSize: 14, cursor: 'pointer' }}
                >
                  {resendState === 'sending' ? 'Sending…' : 'Resend confirmation email'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

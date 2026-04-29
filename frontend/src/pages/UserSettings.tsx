import { useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { User } from '../api/types'
import PasswordStrengthMeter, { scorePassword } from '../components/PasswordStrengthMeter'

export default function UserSettings() {
  const { user } = useOutletContext<{ user: User }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  const isForced = user.force_password_change === true
  const { score } = scorePassword(newPassword)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (newPassword !== confirm) { setError('Passwords do not match'); return }
    if (score < 3) { setError('Please choose a stronger password'); return }
    setLoading(true)
    try {
      await api.auth.changePassword(oldPassword, newPassword)
      setSuccess(true)
      // Refresh user so force_password_change is cleared
      await qc.invalidateQueries({ queryKey: ['auth-me'] })
      setTimeout(() => navigate('/'), 1500)
    } catch (err: any) {
      setError(err.message ?? 'Password change failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 400 }}>
        {!isForced && (
          <button
            onClick={() => navigate('/')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0, marginBottom: 20, fontSize: 14 }}
          >
            ← Back
          </button>
        )}

        <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>
          {isForced ? 'Set your password' : 'Change password'}
        </h1>

        {isForced && (
          <div style={{ background: 'rgba(107,125,224,0.12)', border: '1px solid rgba(107,125,224,0.3)', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
            <p style={{ fontSize: 13, margin: 0, color: 'var(--text)' }}>
              Your account was created by an administrator. Please set a personal password before continuing.
            </p>
          </div>
        )}

        <div style={{ background: 'rgba(192,0,0,0.06)', border: '1px solid rgba(192,0,0,0.2)', borderRadius: 6, padding: '10px 14px', marginBottom: 20 }}>
          <p style={{ fontSize: 13, margin: 0, color: 'var(--text)' }}>
            <strong>Your data is encrypted with your password.</strong> If you forget it, your preference profiles and ratings cannot be recovered.
            Consider <strong>exporting your profiles</strong> as a backup before changing your password.
          </p>
        </div>

        {success && (
          <div style={{ background: 'rgba(46,125,50,0.1)', border: '1px solid #2e7d32', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
            <span style={{ fontSize: 13, color: '#2e7d32' }}>Password changed. Redirecting…</span>
          </div>
        )}

        {error && (
          <div style={{ background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: 6, padding: '10px 14px', marginBottom: 16 }}>
            <span style={{ fontSize: 13, color: '#c00' }}>{error}</span>
          </div>
        )}

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>
              {isForced ? 'Temporary password' : 'Current password'}
            </label>
            <input
              type="password"
              value={oldPassword}
              onChange={e => setOldPassword(e.target.value)}
              required
              autoFocus
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>New password</label>
            <input
              type="password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              required
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
            <PasswordStrengthMeter password={newPassword} />
            <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '4px 0 0' }}>
              Use a passphrase — three or more random words work great.
            </p>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>Confirm new password</label>
            <input
              type="password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              required
              style={{ width: '100%', padding: '8px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box' }}
            />
            {confirm && newPassword !== confirm && (
              <p style={{ fontSize: 11, color: '#c00', margin: '3px 0 0' }}>Passwords do not match</p>
            )}
          </div>
          <button
            type="submit"
            disabled={loading || success || score < 3 || newPassword !== confirm}
            style={{
              padding: '9px 0', background: '#6b7de0', color: '#fff', border: 'none',
              borderRadius: 4, fontSize: 14,
              cursor: loading || success || score < 3 || newPassword !== confirm ? 'default' : 'pointer',
              marginTop: 4, opacity: score < 3 || (!!confirm && newPassword !== confirm) ? 0.6 : 1,
            }}
          >
            {loading ? 'Changing…' : 'Change password'}
          </button>
        </form>

        <p style={{ marginTop: 16, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          Signed in as <strong>{user.email}</strong>
        </p>
      </div>
    </div>
  )
}

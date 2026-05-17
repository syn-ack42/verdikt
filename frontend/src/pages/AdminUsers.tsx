import { useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { User } from '../api/types'
import PasswordStrengthMeter, { scorePassword } from '../components/PasswordStrengthMeter'

type GrantModal = { userId: string; email: string }
type LimitsModal = { userId: string; email: string; currentGrant: number | null; currentExpiry: number; currentStorage: number | null }

export default function AdminUsers() {
  const { user: me } = useOutletContext<{ user: User }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; email: string } | null>(null)
  const [deleteInput, setDeleteInput] = useState('')
  const [grantModal, setGrantModal] = useState<GrantModal | null>(null)
  const [grantAmount, setGrantAmount] = useState('10000')
  const [grantExpiry, setGrantExpiry] = useState('')
  const [grantNote, setGrantNote] = useState('')
  const [limitsModal, setLimitsModal] = useState<LimitsModal | null>(null)
  const [limitsGrant, setLimitsGrant] = useState('')
  const [limitsExpiry, setLimitsExpiry] = useState('7')
  const [limitsStorage, setLimitsStorage] = useState('')
  const [showAddUser, setShowAddUser] = useState(false)
  const [addEmail, setAddEmail] = useState('')
  const [addPassword, setAddPassword] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  if (!me.is_admin) return <div style={{ padding: 24 }}>Access denied.</div>

  const { data: users, isLoading } = useQuery({ queryKey: ['admin-users'], queryFn: () => api.admin.listUsers() })
  const refetch = () => qc.invalidateQueries({ queryKey: ['admin-users'] })

  const block = useMutation({ mutationFn: (id: string) => api.admin.blockUser(id), onSuccess: refetch })
  const unblock = useMutation({ mutationFn: (id: string) => api.admin.unblockUser(id), onSuccess: refetch })
  const del = useMutation({ mutationFn: (id: string) => api.admin.deleteUser(id), onSuccess: () => { refetch(); setDeleteConfirm(null); setDeleteInput('') } })
  const promote = useMutation({ mutationFn: (id: string) => api.admin.promoteUser(id), onSuccess: refetch })
  const demote = useMutation({ mutationFn: (id: string) => api.admin.demoteUser(id), onSuccess: refetch })

  const createGrant = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof api.admin.createGrant>[1] }) =>
      api.admin.createGrant(id, body),
    onSuccess: () => { refetch(); setGrantModal(null) },
  })

  const updateLimits = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof api.admin.updateUserLimits>[1] }) =>
      api.admin.updateUserLimits(id, body),
    onSuccess: () => { refetch(); setLimitsModal(null) },
  })

  const addUser = useMutation({
    mutationFn: () => api.admin.createUser(addEmail, addPassword),
    onSuccess: () => { refetch(); setShowAddUser(false); setAddEmail(''); setAddPassword(''); setAddError(null) },
    onError: (err: any) => setAddError(err.message ?? 'Failed to create user'),
  })

  const { score: addScore } = scorePassword(addPassword)

  const btnStyle = (color?: string): React.CSSProperties => ({
    padding: '4px 10px', fontSize: 12, borderRadius: 4,
    border: '1px solid var(--border)', background: 'none',
    cursor: 'pointer', color: color ?? 'var(--text)',
  })

  const inputStyle: React.CSSProperties = {
    display: 'block', width: '100%', padding: '7px 10px', borderRadius: 4,
    border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
    fontSize: 14, boxSizing: 'border-box', marginBottom: 10,
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <button onClick={() => navigate('/')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0 }}>
          ← Projects
        </button>
        <h2 style={{ margin: 0, flex: 1 }}>Users</h2>
        {users && <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{users.length} total</span>}
        <button onClick={() => setShowAddUser(true)}
          style={{ padding: '6px 14px', borderRadius: 4, fontSize: 13, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: '#2e7d32' }}>
          + Add User
        </button>
      </div>

      {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}

      {users && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          {users.map((u, i) => (
            <div key={u.id} style={{
              padding: '10px 14px',
              borderBottom: i < users.length - 1 ? '1px solid var(--border)' : 'none',
              background: u.id === me.id ? 'var(--surface, rgba(128,128,128,0.04))' : 'transparent',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {u.email}
                    {u.id === me.id && <span style={{ marginLeft: 8, fontSize: 11, color: '#6b7de0' }}>you</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
                    <span>{u.created_at?.slice(0, 10)}</span>
                    {u.is_founding_admin && <span style={{ background: 'rgba(107,125,224,0.15)', color: '#6b7de0', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>founder</span>}
                    {u.is_admin && !u.is_founding_admin && <span style={{ background: 'rgba(107,125,224,0.15)', color: '#6b7de0', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>admin</span>}
                    {u.is_blocked && <span style={{ background: 'rgba(192,0,0,0.1)', color: '#c00', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>blocked</span>}
                    {!u.email_confirmed && <span style={{ background: 'rgba(192,120,0,0.15)', color: '#c07000', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>unconfirmed</span>}
                    {u.force_password_change && <span style={{ background: 'rgba(192,0,0,0.1)', color: '#c00', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>must set password</span>}
                    {u.daily_token_grant != null && (
                      <span style={{ fontSize: 11 }}>{u.daily_token_grant.toLocaleString()} tokens/day</span>
                    )}
                    {u.storage_limit_bytes != null && (
                      <span style={{ fontSize: 11 }}>{(u.storage_limit_bytes / (1024 * 1024)).toFixed(0)} MB storage</span>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                  <button
                    onClick={() => { setGrantModal({ userId: u.id, email: u.email }); setGrantAmount('10000'); setGrantExpiry(''); setGrantNote('') }}
                    style={btnStyle('#2e7d32')}
                  >Grant tokens</button>
                  <button
                    onClick={() => {
                      setLimitsModal({ userId: u.id, email: u.email, currentGrant: u.daily_token_grant ?? null, currentExpiry: u.token_grant_expiry_days ?? 7, currentStorage: u.storage_limit_bytes ?? null })
                      setLimitsGrant(u.daily_token_grant != null ? String(u.daily_token_grant) : '')
                      setLimitsExpiry(String(u.token_grant_expiry_days ?? 7))
                      setLimitsStorage(u.storage_limit_bytes != null ? String(Math.round(u.storage_limit_bytes / (1024 * 1024))) : '')
                    }}
                    style={btnStyle()}
                  >Limits</button>
                  {u.id !== me.id && !u.is_founding_admin && (
                    u.is_admin ? (
                      <button onClick={() => demote.mutate(u.id)} disabled={demote.isPending} style={btnStyle('#b45309')}>
                        Demote admin
                      </button>
                    ) : (
                      <button onClick={() => promote.mutate(u.id)} disabled={promote.isPending} style={btnStyle('#6b7de0')}>
                        Make admin
                      </button>
                    )
                  )}
                  {u.id !== me.id && (
                    u.is_blocked ? (
                      <button onClick={() => unblock.mutate(u.id)} disabled={unblock.isPending} style={btnStyle()}>Unblock</button>
                    ) : (
                      <button onClick={() => block.mutate(u.id)} disabled={block.isPending} style={btnStyle('#b45309')}>Block</button>
                    )
                  )}
                  {u.id !== me.id && (
                    <button onClick={() => { setDeleteConfirm({ id: u.id, email: u.email }); setDeleteInput('') }} style={btnStyle('#c00')}>Delete</button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add user modal */}
      {showAddUser && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setShowAddUser(false) }}>
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(420px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 16 }}>Add user</h3>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--text-muted)' }}>
              The user will be required to change their password on first login.
              No confirmation email is sent.
            </p>
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Email</label>
            <input type="email" value={addEmail} onChange={e => setAddEmail(e.target.value)} autoFocus style={inputStyle} />
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Temporary password</label>
            <input type="password" value={addPassword} onChange={e => setAddPassword(e.target.value)} style={{ ...inputStyle, marginBottom: 4 }} />
            <PasswordStrengthMeter password={addPassword} style={{ marginBottom: 10 }} />
            {addError && <p style={{ color: '#c00', fontSize: 12, marginBottom: 8 }}>{addError}</p>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => addUser.mutate()}
                disabled={addUser.isPending || !addEmail || addScore < 2}
                style={{ padding: '7px 16px', borderRadius: 4, border: 'none', fontSize: 14, cursor: 'pointer', background: '#6b7de0', color: '#fff' }}
              >{addUser.isPending ? 'Creating…' : 'Create'}</button>
              <button onClick={() => { setShowAddUser(false); setAddError(null) }} style={{ padding: '7px 14px', borderRadius: 4, fontSize: 14 }}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Grant tokens modal */}
      {grantModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setGrantModal(null) }}>
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(380px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 16 }}>Grant tokens</h3>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--text-muted)' }}>{grantModal.email}</p>
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Amount</label>
            <input type="number" min={1} value={grantAmount} onChange={e => setGrantAmount(e.target.value)} style={inputStyle} />
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Expires at (leave blank = never)</label>
            <input type="datetime-local" value={grantExpiry} onChange={e => setGrantExpiry(e.target.value)} style={inputStyle} />
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Note (optional)</label>
            <input type="text" value={grantNote} onChange={e => setGrantNote(e.target.value)} style={inputStyle} />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => createGrant.mutate({ id: grantModal.userId, body: { amount: parseInt(grantAmount) || 0, expires_at: grantExpiry ? new Date(grantExpiry).toISOString() : null, note: grantNote || undefined } })}
                disabled={createGrant.isPending || !parseInt(grantAmount)}
                style={{ padding: '7px 16px', borderRadius: 4, border: 'none', fontSize: 14, cursor: 'pointer', background: '#2e7d32', color: '#fff' }}
              >{createGrant.isPending ? 'Granting…' : 'Grant'}</button>
              <button onClick={() => setGrantModal(null)} style={{ padding: '7px 14px', borderRadius: 4, fontSize: 14 }}>Cancel</button>
            </div>
            {createGrant.isError && <p style={{ color: '#c00', fontSize: 12, marginTop: 8 }}>{(createGrant.error as Error).message}</p>}
          </div>
        </div>
      )}

      {/* Token + storage limits modal */}
      {limitsModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setLimitsModal(null) }}>
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(400px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 16 }}>User limits</h3>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--text-muted)' }}>{limitsModal.email}</p>
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Daily token grant (leave blank = use site default)</label>
            <input type="number" min={0} value={limitsGrant} onChange={e => setLimitsGrant(e.target.value)}
              placeholder="site default" style={inputStyle} />
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Token grant expiry (days)</label>
            <input type="number" min={1} value={limitsExpiry} onChange={e => setLimitsExpiry(e.target.value)} style={inputStyle} />
            <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Storage limit (MB, leave blank = site default)</label>
            <input type="number" min={0} value={limitsStorage} onChange={e => setLimitsStorage(e.target.value)}
              placeholder="site default" style={inputStyle} />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => updateLimits.mutate({
                  id: limitsModal.userId,
                  body: {
                    daily_token_grant: limitsGrant ? parseInt(limitsGrant) : null,
                    token_grant_expiry_days: parseInt(limitsExpiry) || 7,
                    storage_limit_bytes: limitsStorage ? parseInt(limitsStorage) * 1024 * 1024 : null,
                  },
                })}
                disabled={updateLimits.isPending}
                style={{ padding: '7px 16px', borderRadius: 4, border: 'none', fontSize: 14, cursor: 'pointer', background: '#6b7de0', color: '#fff' }}
              >{updateLimits.isPending ? 'Saving…' : 'Save'}</button>
              <button onClick={() => setLimitsModal(null)} style={{ padding: '7px 14px', borderRadius: 4, fontSize: 14 }}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      {deleteConfirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setDeleteConfirm(null) }}>
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(420px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>Delete user</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 16px' }}>
              This permanently deletes <strong>{deleteConfirm.email}</strong> and all their data. Type their email to confirm.
            </p>
            <input type="text" value={deleteInput} onChange={e => setDeleteInput(e.target.value)}
              placeholder={deleteConfirm.email}
              style={{ width: '100%', padding: '7px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box', marginBottom: 12 }} />
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => del.mutate(deleteConfirm.id)} disabled={deleteInput !== deleteConfirm.email || del.isPending}
                style={{ padding: '7px 16px', borderRadius: 4, border: 'none', fontSize: 14, cursor: deleteInput === deleteConfirm.email ? 'pointer' : 'default', background: deleteInput === deleteConfirm.email ? '#c00' : 'var(--border)', color: deleteInput === deleteConfirm.email ? '#fff' : 'var(--text-muted)' }}>
                {del.isPending ? 'Deleting…' : 'Delete'}
              </button>
              <button onClick={() => setDeleteConfirm(null)} style={{ padding: '7px 14px', borderRadius: 4, fontSize: 14 }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

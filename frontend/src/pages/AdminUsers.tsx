import { useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { User } from '../api/types'

export default function AdminUsers() {
  const { user: me } = useOutletContext<{ user: User }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; email: string } | null>(null)
  const [deleteInput, setDeleteInput] = useState('')

  if (!me.is_admin) {
    return <div style={{ padding: 24 }}>Access denied.</div>
  }

  const { data: users, isLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api.admin.listUsers(),
  })

  const block = useMutation({
    mutationFn: (id: string) => api.admin.blockUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })
  const unblock = useMutation({
    mutationFn: (id: string) => api.admin.unblockUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })
  const del = useMutation({
    mutationFn: (id: string) => api.admin.deleteUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      setDeleteConfirm(null)
      setDeleteInput('')
    },
  })

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button onClick={() => navigate('/')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7de0', padding: 0 }}>
          ← Projects
        </button>
        <h2 style={{ margin: 0 }}>Users</h2>
        {users && <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{users.length} total</span>}
      </div>

      {isLoading && <p style={{ color: 'var(--text-muted)' }}>Loading…</p>}

      {users && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          {users.map((u, i) => (
            <div
              key={u.id}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 14px',
                borderBottom: i < users.length - 1 ? '1px solid var(--border)' : 'none',
                background: u.id === me.id ? 'var(--surface, rgba(128,128,128,0.04))' : 'transparent',
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 500, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {u.email}
                  {u.id === me.id && <span style={{ marginLeft: 8, fontSize: 11, color: '#6b7de0' }}>you</span>}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  {u.created_at?.slice(0, 10)}
                  {u.is_admin && <span style={{ marginLeft: 8, background: 'rgba(107,125,224,0.15)', color: '#6b7de0', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>admin</span>}
                  {u.is_blocked && <span style={{ marginLeft: 6, background: 'rgba(192,0,0,0.1)', color: '#c00', fontSize: 10, padding: '1px 5px', borderRadius: 3 }}>blocked</span>}
                </div>
              </div>
              {u.id !== me.id && (
                <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                  {u.is_blocked ? (
                    <button
                      onClick={() => unblock.mutate(u.id)}
                      disabled={unblock.isPending}
                      style={{ padding: '4px 10px', fontSize: 12, borderRadius: 4, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: 'var(--text)' }}
                    >
                      Unblock
                    </button>
                  ) : (
                    <button
                      onClick={() => block.mutate(u.id)}
                      disabled={block.isPending}
                      style={{ padding: '4px 10px', fontSize: 12, borderRadius: 4, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: '#b45309' }}
                    >
                      Block
                    </button>
                  )}
                  <button
                    onClick={() => { setDeleteConfirm({ id: u.id, email: u.email }); setDeleteInput('') }}
                    style={{ padding: '4px 10px', fontSize: 12, borderRadius: 4, border: '1px solid var(--border)', background: 'none', cursor: 'pointer', color: '#c00' }}
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Delete confirmation dialog */}
      {deleteConfirm && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 24 }}
          onClick={e => { if (e.target === e.currentTarget) setDeleteConfirm(null) }}
        >
          <div style={{ background: 'var(--modal-bg)', borderRadius: 8, padding: 24, width: 'min(420px, 100%)', border: '1px solid var(--border)' }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>Delete user</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '0 0 16px' }}>
              This permanently deletes <strong>{deleteConfirm.email}</strong> and all their data. Type their email to confirm.
            </p>
            <input
              type="text"
              value={deleteInput}
              onChange={e => setDeleteInput(e.target.value)}
              placeholder={deleteConfirm.email}
              style={{ width: '100%', padding: '7px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, boxSizing: 'border-box', marginBottom: 12 }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => del.mutate(deleteConfirm.id)}
                disabled={deleteInput !== deleteConfirm.email || del.isPending}
                style={{
                  padding: '7px 16px', borderRadius: 4, border: 'none', fontSize: 14, cursor: deleteInput === deleteConfirm.email ? 'pointer' : 'default',
                  background: deleteInput === deleteConfirm.email ? '#c00' : 'var(--border)',
                  color: deleteInput === deleteConfirm.email ? '#fff' : 'var(--text-muted)',
                }}
              >
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

import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import type { User } from '../api/types'

export default function ProtectedRoute() {
  const location = useLocation()
  const { data, isLoading, error } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => api.auth.me(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) return <p style={{ padding: 24 }}>Loading…</p>
  if (error || !data) return <Navigate to="/login" replace />

  const user = data as User

  // Force password change before accessing anything else
  if (user.force_password_change && location.pathname !== '/settings/password') {
    return <Navigate to="/settings/password" replace />
  }

  return <Outlet context={{ user }} />
}

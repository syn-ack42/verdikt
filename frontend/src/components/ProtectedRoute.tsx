import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet } from 'react-router-dom'
import { api } from '../api/client'
import type { User } from '../api/types'

export default function ProtectedRoute() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => api.auth.me(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) return <p style={{ padding: 24 }}>Loading…</p>
  if (error || !data) return <Navigate to="/login" replace />
  return <Outlet context={{ user: data as User }} />
}

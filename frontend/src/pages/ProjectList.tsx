import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

export default function ProjectList() {
  const qc = useQueryClient()
  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: api.projects.list,
  })

  const del = useMutation({
    mutationFn: (id: string) => api.projects.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })

  if (isLoading) return <p>Loading…</p>

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Verdikt</h1>
        <Link to="/projects/new">
          <button>New Project</button>
        </Link>
      </div>
      {!projects?.length && <p style={{ color: '#888' }}>No projects yet. Create one to get started.</p>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {projects?.map(p => (
          <div key={p.id} style={{ border: '1px solid #e0e0e0', borderRadius: 8, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ margin: '0 0 4px' }}>{p.name}</h3>
                {p.description && <p style={{ margin: '0 0 8px', color: '#666', fontSize: 14 }}>{p.description}</p>}
                <span style={{ fontSize: 12, color: '#999' }}>
                  {p.domain} · {p.rating_dimensions.length} dimensions · created {p.created_at.slice(0, 10)}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Link to={`/projects/${p.id}`}><button>Dashboard</button></Link>
                <Link to={`/projects/${p.id}/rate`}><button>Rate</button></Link>
                <button
                  onClick={() => confirm(`Delete "${p.name}"?`) && del.mutate(p.id)}
                  style={{ color: '#c00' }}
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

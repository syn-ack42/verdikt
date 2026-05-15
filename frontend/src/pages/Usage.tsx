import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { TokenWindowStats } from '../api/types'

function fmt(n: number | null | undefined): string {
  if (n == null || n === 0) return '—'
  if (n < 0.0001) return '<$0.0001'
  return '$' + n.toFixed(4)
}

function StatCard({ label, stats }: { label: string; stats: TokenWindowStats }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '14px 18px', minWidth: 140 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.total.toLocaleString()}</div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
        {stats.prompt.toLocaleString()} prompt · {stats.completion.toLocaleString()} completion
      </div>
      {stats.cost_usd != null && stats.cost_usd > 0 && (
        <div style={{ fontSize: 12, color: '#7c3aed', marginTop: 6, fontWeight: 500 }}>
          {fmt(stats.cost_usd)} USD
        </div>
      )}
    </div>
  )
}

export default function Usage() {
  const navigate = useNavigate()
  const { data: usage, isLoading } = useQuery({ queryKey: ['usage'], queryFn: api.usage.get })

  const hasCost = usage?.by_project.some(p => p.all_time.cost_usd != null && p.all_time.cost_usd > 0)

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button
          onClick={() => navigate(-1)}
          style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 12px', cursor: 'pointer', fontSize: 14 }}
        >← Back</button>
        <h1 style={{ margin: 0 }}>Token Usage</h1>
      </div>

      {isLoading && <p>Loading…</p>}

      {usage && (
        <>
          <div style={{ marginBottom: 24 }}>
            {usage.balance === null ? (
              <div style={{ background: 'rgba(46,125,50,0.1)', border: '1px solid rgba(46,125,50,0.3)', borderRadius: 8, padding: '12px 16px', display: 'inline-block' }}>
                <span style={{ color: '#2e7d32', fontWeight: 600 }}>Unlimited tokens</span>
                <span style={{ color: 'var(--text-muted)', fontSize: 13, marginLeft: 8 }}>No daily limit set for your account</span>
              </div>
            ) : (
              <div style={{ background: usage.balance > 0 ? 'rgba(107,125,224,0.08)' : 'rgba(192,0,0,0.08)', border: `1px solid ${usage.balance > 0 ? 'rgba(107,125,224,0.3)' : 'rgba(192,0,0,0.3)'}`, borderRadius: 8, padding: '12px 16px', display: 'inline-block' }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: usage.balance > 0 ? '#6b7de0' : '#c00' }}>
                  {usage.balance.toLocaleString()}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: 13, marginLeft: 8 }}>tokens remaining</span>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 32 }}>
            <StatCard label="Today" stats={usage.today} />
            <StatCard label="This Week" stats={usage.week} />
            <StatCard label="This Month" stats={usage.month} />
            <StatCard label="All Time" stats={usage.all_time} />
          </div>

          {usage.by_project.length > 0 && (
            <>
              <h2 style={{ margin: '0 0 12px', fontSize: 16 }}>By Project</h2>
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                <div style={{ display: 'grid', gridTemplateColumns: hasCost ? '1fr auto auto auto auto' : '1fr auto auto auto', gap: 0, background: 'var(--surface, rgba(255,255,255,0.04))' }}>
                  {['Project', 'Prompt', 'Completion', 'Total', ...(hasCost ? ['Cost (USD)'] : [])].map(h => (
                    <div key={h} style={{ padding: '8px 14px', fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{h}</div>
                  ))}
                </div>
                {usage.by_project.map((p, i) => (
                  <div key={p.project_id} style={{ display: 'grid', gridTemplateColumns: hasCost ? '1fr auto auto auto auto' : '1fr auto auto auto', borderTop: '1px solid var(--border)', background: i % 2 === 0 ? 'transparent' : 'var(--surface, rgba(255,255,255,0.02))' }}>
                    <div style={{ padding: '10px 14px', fontSize: 13 }}>{p.project_name || p.project_id}</div>
                    <div style={{ padding: '10px 14px', fontSize: 13, color: 'var(--text-muted)' }}>{p.all_time.prompt.toLocaleString()}</div>
                    <div style={{ padding: '10px 14px', fontSize: 13, color: 'var(--text-muted)' }}>{p.all_time.completion.toLocaleString()}</div>
                    <div style={{ padding: '10px 14px', fontSize: 13, fontWeight: 600 }}>{p.all_time.total.toLocaleString()}</div>
                    {hasCost && (
                      <div style={{ padding: '10px 14px', fontSize: 13, color: p.all_time.cost_usd ? '#7c3aed' : 'var(--text-muted)' }}>
                        {fmt(p.all_time.cost_usd)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {usage.by_project.length === 0 && usage.all_time.total === 0 && (
            <p style={{ color: 'var(--text-muted)' }}>No token usage recorded yet.</p>
          )}
        </>
      )}
    </div>
  )
}

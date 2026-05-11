import type {
  AIRatingStatus, AppConfig, BatchIngestEvent, BatchIngestStatus, CrystalliseStatus, DiscoveryStatus, IngestResult, ModelCatalogEntry, NextChunkResponse, PipelineResult, PipelineStreamEvent,
  PluginConfig, PluginConfigMap, PluginIngestEvent, PluginInfo, PreferenceProfile, Project, ProjectDefaults, RatedChunksResponse, RatingCounts, Rating, SiteSettings, StorageListing,
  TokenGrant, UpdatePluginEvent, UpdatePluginStatus, UsageSummary, User, WorkChunk, WorkDetail, WritebackResult, WorksListResponse,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? `${import.meta.env.BASE_URL}api`

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'include',
    signal,
  })
  if (res.status === 401) {
    // Redirect to login on auth failure (unless we're already there)
    if (!window.location.pathname.startsWith(`${import.meta.env.BASE_URL}login`)) {
      window.location.href = `${import.meta.env.BASE_URL}login`
    }
    const err = await res.json().catch(() => ({ detail: 'Not authenticated' }))
    throw Object.assign(new Error(err.detail ?? 'Not authenticated'), { status: 401 })
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw Object.assign(new Error(err.detail ?? res.statusText), { status: res.status })
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

async function streamFetch(path: string, opts: RequestInit, onEvent: (e: unknown) => void): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { ...opts, credentials: 'include' })
  if (res.status === 401 && !window.location.pathname.startsWith(`${import.meta.env.BASE_URL}login`)) {
    window.location.href = `${import.meta.env.BASE_URL}login`
    return
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw Object.assign(new Error(err.detail ?? res.statusText), { status: res.status })
  }
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()!
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { onEvent(JSON.parse(line.slice(6))) } catch { /* skip malformed */ }
      }
    }
  }
}

export const api = {
  auth: {
    me: () => req<User>('GET', '/auth/me'),
    login: (email: string, password: string) =>
      req<User>('POST', '/auth/login', { email, password }),
    register: (email: string, password: string) =>
      req<{ id?: string; email?: string; is_admin?: boolean; pending_confirmation?: boolean }>('POST', '/auth/register', { email, password }),
    logout: () => req<{ ok: boolean }>('POST', '/auth/logout'),
    confirmEmail: (token: string) => req<{ ok: boolean; email: string }>('POST', '/auth/confirm-email', { token }),
    changePassword: (old_password: string, new_password: string) =>
      req<{ ok: boolean }>('POST', '/auth/change-password', { old_password, new_password }),
    oauthProviders: () => req<string[]>('GET', '/auth/oauth/providers'),
    oauthAuthorizeUrl: (provider: string) => `${BASE}/auth/oauth/${provider}/authorize`,
  },
  admin: {
    listUsers: () => req<User[]>('GET', '/admin/users'),
    createUser: (email: string, password: string) =>
      req<User>('POST', '/admin/users', { email, password }),
    blockUser: (id: string) => req<User>('POST', `/admin/users/${id}/block`),
    unblockUser: (id: string) => req<User>('POST', `/admin/users/${id}/unblock`),
    deleteUser: (id: string) => req<{ ok: boolean }>('DELETE', `/admin/users/${id}`),
    promoteUser: (id: string) => req<User>('POST', `/admin/users/${id}/promote`),
    demoteUser: (id: string) => req<User>('POST', `/admin/users/${id}/demote`),
    updateUserLimits: (id: string, body: { daily_token_grant?: number | null; token_grant_expiry_days?: number; storage_limit_bytes?: number | null }) =>
      req<User>('PATCH', `/admin/users/${id}/limits`, body),
    createGrant: (id: string, body: { amount: number; expires_at?: string | null; note?: string }) =>
      req<TokenGrant>('POST', `/admin/users/${id}/grants`, body),
    getUserUsage: (id: string) => req<UsageSummary>('GET', `/admin/users/${id}/usage`),
    getSettings: () => req<SiteSettings>('GET', '/admin/settings'),
    updateSettings: (body: Partial<SiteSettings>) => req<SiteSettings>('PUT', '/admin/settings', body),
    testSmtp: () => req<{ ok: boolean }>('POST', '/admin/settings/test-smtp'),
    syncModels: () => req<ModelCatalogEntry[]>('POST', '/admin/models/sync'),
    listModels: () => req<ModelCatalogEntry[]>('GET', '/admin/models'),
    createModel: (body: { id: string; type: string; domain: string; display_name: string; description?: string; source?: string }) =>
      req<ModelCatalogEntry>('POST', '/admin/models', body),
    updateModel: (id: string, body: Partial<ModelCatalogEntry>) =>
      req<ModelCatalogEntry>('PATCH', `/admin/models/${encodeURIComponent(id)}`, body),
  },
  usage: {
    get: () => req<UsageSummary>('GET', '/usage'),
  },
  models: {
    defaults: () => req<{ llm_by_domain: Record<string, string | null> }>('GET', '/models/defaults'),
    domainAvailability: () => req<Record<string, boolean>>('GET', '/models/domain-availability'),
    list: (type?: string, domain?: string) => {
      const p = new URLSearchParams()
      if (type) p.set('type', type)
      if (domain) p.set('domain', domain)
      const qs = p.toString()
      return req<ModelCatalogEntry[]>('GET', `/models${qs ? `?${qs}` : ''}`)
    },
  },
  projects: {
    defaults: () => req<ProjectDefaults>('GET', '/projects/defaults'),
    list: () => req<Project[]>('GET', '/projects'),
    get: (id: string) => req<Project>('GET', `/projects/${id}`),
    create: (body: Partial<Project>) => req<Project>('POST', '/projects', body),
    update: (id: string, body: Partial<Project> & { dimension_renames?: Record<string, string> }) => req<Project>('PUT', `/projects/${id}`, body),
    delete: (id: string) => req<void>('DELETE', `/projects/${id}`),
    exportUrl: (id: string) => `${BASE}/projects/${id}/export`,
    importProject: (data: unknown) => req<{ project_id: string; materials_imported: number; ratings_imported: number; profiles_imported: number; note: string }>('POST', '/projects/import', data),
  },
  works: {
    list: (projectId: string, phase?: string, sortBy?: string, sortDir?: 'asc' | 'desc', limit = 50, offset = 0, search?: string) => {
      const params = new URLSearchParams()
      if (phase) params.set('phase', phase)
      if (sortBy) params.set('sort_by', sortBy)
      if (sortDir) params.set('sort_dir', sortDir)
      params.set('limit', String(limit))
      params.set('offset', String(offset))
      if (search && search.trim()) params.set('search', search.trim())
      return req<WorksListResponse>('GET', `/projects/${projectId}/works?${params}`)
    },
    chunkContent: (projectId: string, chunkId: string) =>
      req<{ content: string | null; domain: 'text' | 'image' }>('GET', `/projects/${projectId}/works/chunk/${encodeURIComponent(chunkId)}`),
    ingest: (projectId: string, storagePaths: string[]) =>
      req<IngestResult>('POST', `/projects/${projectId}/works/ingest`, { storage_paths: storagePaths }),
    detail: (projectId: string, ref: string) =>
      req<WorkDetail>('GET', `/projects/${projectId}/works/${encodeURIComponent(ref)}/detail`),
    chunks: (projectId: string, ref: string) =>
      req<WorkChunk[]>('GET', `/projects/${projectId}/works/${encodeURIComponent(ref)}/chunks`),
    delete: (projectId: string, ref: string) =>
      req<void>('DELETE', `/projects/${projectId}/works/${encodeURIComponent(ref)}`),
    getPluginConfig: (projectId: string) =>
      req<PluginConfigMap>('GET', `/projects/${projectId}/works/plugin-config`),
    savePluginConfig: (projectId: string, pluginName: string, config: Record<string, unknown>) =>
      req<PluginConfig>('PUT', `/projects/${projectId}/works/plugin-config`, { plugin_name: pluginName, config }),
    ingestPlugin: (projectId: string, pluginName: string, config: Record<string, unknown>) =>
      req<IngestResult>('POST', `/projects/${projectId}/works/ingest-plugin`, { plugin_name: pluginName, config }),
    ingestPluginStream: (projectId: string, pluginName: string, config: Record<string, unknown>, onEvent: (e: PluginIngestEvent) => void) =>
      streamFetch(`/projects/${projectId}/works/ingest-plugin/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginName, config }),
      }, onEvent as (e: unknown) => void),
    getUpdateStatus: (projectId: string) =>
      req<UpdatePluginStatus>('GET', `/projects/${projectId}/works/update-plugin/status`),
    updatePluginStream: (projectId: string, onEvent: (e: UpdatePluginEvent) => void) =>
      streamFetch(`/projects/${projectId}/works/update-plugin/stream`, { method: 'POST' }, onEvent as (e: unknown) => void),
  },
  plugins: {
    list: (domain?: string) => req<PluginInfo[]>('GET', `/plugins${domain ? `?domain=${domain}` : ''}`),
    help: (pluginName: string) => req<{ markdown: string }>('GET', `/plugins/${encodeURIComponent(pluginName)}/help`),
    runAction: (pluginName: string, projectId: string, actionName: string, options: Record<string, unknown>) =>
      req<WritebackResult>('POST', `/plugins/${encodeURIComponent(pluginName)}/projects/${encodeURIComponent(projectId)}/actions/${encodeURIComponent(actionName)}`, options),
  },
  batchIngest: {
    status: (projectId: string) =>
      req<BatchIngestStatus>('GET', `/projects/${projectId}/batch-ingest/status`),
    startStream: (projectId: string, onEvent: (e: BatchIngestEvent) => void) =>
      streamFetch(`/projects/${projectId}/batch-ingest/start/stream`, { method: 'POST' }, onEvent as (e: unknown) => void),
    stop: (projectId: string) =>
      req<{ ok: boolean }>('POST', `/projects/${projectId}/batch-ingest/stop`),
    reset: (projectId: string) =>
      req<{ status: string }>('POST', `/projects/${projectId}/batch-ingest/reset`),
  },
  pipeline: {
    run: (projectId: string) => req<PipelineResult>('POST', `/projects/${projectId}/pipeline/run`),
    runStream: (projectId: string, onEvent: (e: PipelineStreamEvent) => void) =>
      streamFetch(`/projects/${projectId}/pipeline/run/stream`, { method: 'POST' }, onEvent as (e: unknown) => void),
  },
  ratings: {
    next: (projectId: string, mode: 'normal' | 'confirm_ai' = 'normal') =>
      req<NextChunkResponse>('GET', `/projects/${projectId}/ratings/next?mode=${mode}`),
    submit: (projectId: string, body: {
      chunk_id: string
      material_item_id: string
      dimension_scores: Record<string, number>
      skipped?: boolean
      skip_reason?: string
      ai_rating_id?: string
    }) => req<Rating>('POST', `/projects/${projectId}/ratings`, body),
    aiPreview: (projectId: string, chunkId: string, materialItemId: string, signal?: AbortSignal) =>
      req<{ ai_rating_id: string; dimension_scores: Record<string, number>; explanations: Record<string, string> }>(
        'POST', `/projects/${projectId}/ai-rating/preview`,
        { chunk_id: chunkId, material_item_id: materialItemId },
        signal,
      ),
    rateChunkAI: (projectId: string, chunkId: string, materialItemId: string) =>
      req<{ ai_rating_id: string; dimension_scores: Record<string, number>; explanations: Record<string, string> }>(
        'POST', `/projects/${projectId}/ai-rating/rate-chunk`,
        { chunk_id: chunkId, material_item_id: materialItemId },
      ),
    list: (projectId: string) => req<Rating[]>('GET', `/projects/${projectId}/ratings`),
    counts: (projectId: string) => req<RatingCounts>('GET', `/projects/${projectId}/ratings/counts`),
    ratedChunks: (projectId: string, workSeq?: number, sortBy = 'chunk_position', sortDir = 'asc', limit = 50, offset = 0) => {
      const p = new URLSearchParams()
      if (workSeq != null) p.set('work_seq', String(workSeq))
      p.set('sort_by', sortBy)
      p.set('sort_dir', sortDir)
      p.set('limit', String(limit))
      p.set('offset', String(offset))
      return req<RatedChunksResponse>('GET', `/projects/${projectId}/ratings/rated-chunks?${p}`)
    },
    updateRating: (projectId: string, ratingId: string, dimensionScores: Record<string, number>) =>
      req<Rating>('PUT', `/projects/${projectId}/ratings/${ratingId}`, { dimension_scores: dimensionScores }),
  },
  aiRating: {
    start: (projectId: string, opts?: { batch_size?: number; random_fraction?: number }) =>
      req<{ status: string }>('POST', `/projects/${projectId}/ai-rating/start`, opts ?? {}),
    stop: (projectId: string) =>
      req<{ status: string }>('POST', `/projects/${projectId}/ai-rating/stop`, {}),
    status: (projectId: string) =>
      req<AIRatingStatus>('GET', `/projects/${projectId}/ai-rating/status`),
  },
  profile: {
    get: (projectId: string) => req<PreferenceProfile>('GET', `/projects/${projectId}/profile`),
    versions: (projectId: string) => req<PreferenceProfile[]>('GET', `/projects/${projectId}/profile/versions`),
    crystallise: (projectId: string) => req<PreferenceProfile>('POST', `/projects/${projectId}/profile/crystallise`),
    crystalliseStatus: (projectId: string) => req<CrystalliseStatus>('GET', `/projects/${projectId}/profile/crystallise/status`),
    update: (projectId: string, body: Partial<PreferenceProfile>) =>
      req<PreferenceProfile>('PUT', `/projects/${projectId}/profile`, body),
    restore: (projectId: string, versionId: string) =>
      req<PreferenceProfile>('POST', `/projects/${projectId}/profile/versions/${versionId}/restore`),
  },
  storage: {
    downloadUrl: (path: string) => `${BASE}/storage/download?path=${encodeURIComponent(path)}`,
    list: (path = '/') => req<StorageListing>('GET', `/storage?path=${encodeURIComponent(path)}`),
    mkdir: (path: string) => req<{ path: string }>('POST', `/storage/mkdir?path=${encodeURIComponent(path)}`),
    delete: (path: string) => req<void>('DELETE', `/storage?path=${encodeURIComponent(path)}`),
    upload: async (path: string, files: FileList | File[]): Promise<{ uploaded: string[]; path: string }> => {
      const form = new FormData()
      form.append('path', path)
      for (const file of Array.from(files)) {
        form.append('files', file, file.name)
      }
      const res = await fetch(`${BASE}/storage/upload`, { method: 'POST', body: form, credentials: 'include' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw Object.assign(new Error(err.detail ?? res.statusText), { status: res.status })
      }
      return res.json()
    },
  },
  config: {
    get: () => req<AppConfig>('GET', '/config'),
  },
  discovery: {
    next: (projectId: string) =>
      req<NextChunkResponse>('GET', `/projects/${projectId}/discovery/next`),
    submitRating: (projectId: string, body: { chunk_id: string; material_item_id: string; preference: number; reason?: string }) =>
      req<{ ok: boolean; total: number; liked: number; disliked: number; ready: boolean }>('POST', `/projects/${projectId}/discovery/ratings`, body),
    status: (projectId: string) =>
      req<DiscoveryStatus>('GET', `/projects/${projectId}/discovery/status`),
    startAnalysis: (projectId: string) =>
      req<{ status: string }>('POST', `/projects/${projectId}/discovery/analyse/start`),
    resumeAnalysis: (projectId: string) =>
      req<{ status: string }>('POST', `/projects/${projectId}/discovery/analyse/resume`),
    cancelAnalysis: (projectId: string) =>
      req<{ ok: boolean }>('POST', `/projects/${projectId}/discovery/analyse/cancel`),
    clearAnalysisResult: (projectId: string) =>
      req<{ ok: boolean }>('DELETE', `/projects/${projectId}/discovery/analyse/result`),
    apply: (projectId: string, body: { dimensions: { name: string; description: string; weight: number }[]; dimension_renames?: Record<string, string> }) =>
      req<{ id: string; name: string; rating_dimensions: { name: string; description: string; weight: number }[] }>('POST', `/projects/${projectId}/discovery/apply`, body),
    reset: (projectId: string) =>
      req<{ ok: boolean }>('POST', `/projects/${projectId}/discovery/reset`),
  },
}

import type {
  AIRatingStatus, CrystalliseStatus, IngestResult, MaterialItemWithStats, NextChunkResponse, PipelineResult, PipelineStreamEvent,
  PluginConfig, PluginConfigMap, PluginIngestEvent, PluginInfo, PreferenceProfile, Project, RatedChunkEntry, Rating, StorageListing,
  UpdatePluginEvent, UpdatePluginStatus, User, WorkDetail,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? '/api'

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
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
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
  if (res.status === 401 && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
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
      req<User>('POST', '/auth/register', { email, password }),
    logout: () => req<{ ok: boolean }>('POST', '/auth/logout'),
  },
  admin: {
    listUsers: () => req<User[]>('GET', '/admin/users'),
    blockUser: (id: string) => req<User>('POST', `/admin/users/${id}/block`),
    unblockUser: (id: string) => req<User>('POST', `/admin/users/${id}/unblock`),
    deleteUser: (id: string) => req<{ ok: boolean }>('DELETE', `/admin/users/${id}`),
  },
  projects: {
    list: () => req<Project[]>('GET', '/projects'),
    get: (id: string) => req<Project>('GET', `/projects/${id}`),
    create: (body: Partial<Project>) => req<Project>('POST', '/projects', body),
    update: (id: string, body: Partial<Project> & { dimension_renames?: Record<string, string> }) => req<Project>('PUT', `/projects/${id}`, body),
    delete: (id: string) => req<void>('DELETE', `/projects/${id}`),
    exportUrl: (id: string) => `${BASE}/projects/${id}/export`,
    importProject: (data: unknown) => req<{ project_id: string; materials_imported: number; ratings_imported: number; profiles_imported: number; note: string }>('POST', '/projects/import', data),
  },
  works: {
    list: (projectId: string, phase?: string, sortBy?: string, sortDir?: 'asc' | 'desc') => {
      const params = new URLSearchParams()
      if (phase) params.set('phase', phase)
      if (sortBy) params.set('sort_by', sortBy)
      if (sortDir) params.set('sort_dir', sortDir)
      const qs = params.toString()
      return req<MaterialItemWithStats[]>('GET', `/projects/${projectId}/works${qs ? `?${qs}` : ''}`)
    },
    ingest: (projectId: string, storagePaths: string[]) =>
      req<IngestResult>('POST', `/projects/${projectId}/works/ingest`, { storage_paths: storagePaths }),
    detail: (projectId: string, ref: string) =>
      req<WorkDetail>('GET', `/projects/${projectId}/works/${encodeURIComponent(ref)}/detail`),
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
    list: () => req<PluginInfo[]>('GET', '/plugins'),
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
    list: (projectId: string) => req<Rating[]>('GET', `/projects/${projectId}/ratings`),
    ratedChunks: (projectId: string, workSeq?: number) =>
      req<RatedChunkEntry[]>('GET', `/projects/${projectId}/ratings/rated-chunks${workSeq != null ? `?work_seq=${workSeq}` : ''}`),
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
}

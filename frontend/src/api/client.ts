import type {
  IngestResult, MaterialItem, NextChunkResponse, PipelineResult, PipelineStreamEvent,
  PluginConfig, PluginIngestEvent, PluginInfo, PreferenceProfile, Project, Rating, StorageListing, UpdateResult, WorkDetail,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? '/api'

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw Object.assign(new Error(err.detail ?? res.statusText), { status: res.status })
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  projects: {
    list: () => req<Project[]>('GET', '/projects'),
    get: (id: string) => req<Project>('GET', `/projects/${id}`),
    create: (body: Partial<Project>) => req<Project>('POST', '/projects', body),
    update: (id: string, body: Partial<Project> & { dimension_renames?: Record<string, string> }) => req<Project>('PUT', `/projects/${id}`, body),
    delete: (id: string) => req<void>('DELETE', `/projects/${id}`),
  },
  works: {
    list: (projectId: string, phase?: string) =>
      req<MaterialItem[]>('GET', `/projects/${projectId}/works${phase ? `?phase=${phase}` : ''}`),
    ingest: (projectId: string, storagePaths: string[]) =>
      req<IngestResult>('POST', `/projects/${projectId}/works/ingest`, { storage_paths: storagePaths }),
    detail: (projectId: string, ref: string) =>
      req<WorkDetail>('GET', `/projects/${projectId}/works/${encodeURIComponent(ref)}/detail`),
    delete: (projectId: string, ref: string) =>
      req<void>('DELETE', `/projects/${projectId}/works/${encodeURIComponent(ref)}`),
    getPluginConfig: (projectId: string) =>
      req<PluginConfig | null>('GET', `/projects/${projectId}/works/plugin-config`),
    savePluginConfig: (projectId: string, pluginName: string, config: Record<string, unknown>) =>
      req<PluginConfig>('PUT', `/projects/${projectId}/works/plugin-config`, { plugin_name: pluginName, config }),
    ingestPlugin: (projectId: string, pluginName: string, config: Record<string, unknown>) =>
      req<IngestResult>('POST', `/projects/${projectId}/works/ingest-plugin`, { plugin_name: pluginName, config }),
    ingestPluginStream: async (
      projectId: string,
      pluginName: string,
      config: Record<string, unknown>,
      onEvent: (e: PluginIngestEvent) => void,
    ): Promise<void> => {
      const res = await fetch(`${BASE}/projects/${projectId}/works/ingest-plugin/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginName, config }),
      })
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
    },
    updatePlugin: (projectId: string) =>
      req<UpdateResult>('POST', `/projects/${projectId}/works/update-plugin`),
  },
  plugins: {
    list: () => req<PluginInfo[]>('GET', '/plugins'),
  },
  pipeline: {
    run: (projectId: string) => req<PipelineResult>('POST', `/projects/${projectId}/pipeline/run`),
    runStream: async (projectId: string, onEvent: (e: PipelineStreamEvent) => void): Promise<void> => {
      const res = await fetch(`${BASE}/projects/${projectId}/pipeline/run/stream`, { method: 'POST' })
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
    },
  },
  ratings: {
    next: (projectId: string) => req<NextChunkResponse>('GET', `/projects/${projectId}/ratings/next`),
    submit: (projectId: string, body: {
      chunk_id: string
      material_item_id: string
      dimension_scores: Record<string, number>
      skipped?: boolean
      skip_reason?: string
    }) => req<Rating>('POST', `/projects/${projectId}/ratings`, body),
    list: (projectId: string) => req<Rating[]>('GET', `/projects/${projectId}/ratings`),
  },
  profile: {
    get: (projectId: string) => req<PreferenceProfile>('GET', `/projects/${projectId}/profile`),
    versions: (projectId: string) => req<PreferenceProfile[]>('GET', `/projects/${projectId}/profile/versions`),
    crystallise: (projectId: string) => req<PreferenceProfile>('POST', `/projects/${projectId}/profile/crystallise`),
    update: (projectId: string, body: Partial<PreferenceProfile>) =>
      req<PreferenceProfile>('PUT', `/projects/${projectId}/profile`, body),
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
      const res = await fetch(`${BASE}/storage/upload`, { method: 'POST', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw Object.assign(new Error(err.detail ?? res.statusText), { status: res.status })
      }
      return res.json()
    },
  },
}

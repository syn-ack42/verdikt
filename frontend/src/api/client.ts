import type {
  IngestResult, MaterialItem, NextChunkResponse, PipelineResult,
  PreferenceProfile, Project, Rating, StorageListing,
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
    update: (id: string, body: Partial<Project>) => req<Project>('PUT', `/projects/${id}`, body),
    delete: (id: string) => req<void>('DELETE', `/projects/${id}`),
  },
  works: {
    list: (projectId: string, phase?: string) =>
      req<MaterialItem[]>('GET', `/projects/${projectId}/works${phase ? `?phase=${phase}` : ''}`),
    ingest: (projectId: string, storagePaths: string[]) =>
      req<IngestResult>('POST', `/projects/${projectId}/works/ingest`, { storage_paths: storagePaths }),
    delete: (projectId: string, ref: string) =>
      req<void>('DELETE', `/projects/${projectId}/works/${encodeURIComponent(ref)}`),
  },
  pipeline: {
    run: (projectId: string) => req<PipelineResult>('POST', `/projects/${projectId}/pipeline/run`),
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

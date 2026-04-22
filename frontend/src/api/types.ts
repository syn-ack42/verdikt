export interface RatingDimension {
  name: string
  description: string
  weight: number
}

export interface Project {
  id: string
  name: string
  description: string | null
  domain: string
  rating_dimensions: RatingDimension[]
  chunk_min_size: number
  chunk_max_size: number
  crystallisation_threshold: number
  created_at: string
}

export interface MaterialItem {
  id: string
  project_seq: number | null
  source_plugin: string
  source_path: string | null
  work_title: string | null
  author: string | null
  url: string | null
  domain: string
  content_type: string
  pipeline_phase: string
  content_hash: string | null
  ingested_at: string
  plugin_metadata: Record<string, unknown>
}

export interface PipelineResult {
  project_id: string
  total_processed: number
  phases: { phase: string; items_processed: number }[]
}

export type PipelineStreamEvent =
  | { phase: string; status: 'running'; total?: number }
  | { phase: string; status: 'progress'; current: number; total: number }
  | { phase: string; status: 'done'; items_processed: number }
  | { phase: string; status: 'error'; error: string }
  | { complete: true; total_processed: number }

export interface ChunkInfo {
  id: string
  content: string | null
  position: number
  cluster_id: number | null
}

export interface MaterialItemInfo {
  id: string | null
  work_title: string | null
  author: string | null
  source_path: string | null
  project_seq: number | null
}

export interface NextChunkResponse {
  chunk: ChunkInfo
  material_item: MaterialItemInfo
  total_rated: number
  total_chunks: number
}

export interface Rating {
  id: string
  project_id: string
  chunk_id: string
  material_item_id: string
  dimension_scores: Record<string, number>
  skipped: boolean
  skip_reason: string | null
  rated_at: string
}

export interface DimensionProfile {
  name: string
  description: string
  summary: string
  typical_score: number
}

export interface StorageEntry {
  name: string
  path: string
  is_dir: boolean
  size: number
  modified_at: string
}

export interface StorageListing {
  path: string
  entries: StorageEntry[]
}

export interface IngestResult {
  added: number
  updated: number
  skipped: number
}

export interface PreferenceProfile {
  id: string
  project_id: string
  version: number
  dimensions: DimensionProfile[]
  overall_summary: string
  rating_count: number
  created_at: string
}

export interface PluginInfo {
  name: string
  title: string
  description: string
  config_schema: Record<string, unknown>
}

export interface PluginConfig {
  id: string
  project_id: string
  plugin_name: string
  config: Record<string, unknown>
}

export type PluginConfigMap = Record<string, PluginConfig>

export interface UpdateResult {
  updated: number
  unchanged: number
}

export interface UpdatePluginStatus {
  running: boolean
  phase: 'checking' | 'fetching' | null
  updated: number
  unchanged: number
}

export type UpdatePluginEvent =
  | { phase: 'checking'; total: number }
  | { phase: 'fetching'; needs_update: number; unchanged: number }
  | { work: string; status: 'updated' | 'unchanged'; updated: number; unchanged: number }
  | { complete: true; updated: number; unchanged: number }
  | { error: string }

export interface WorkDetail extends MaterialItem {
  content: string | null
  storage_path: string | null
}

export interface RatedChunkEntry {
  rating_id: string
  chunk_id: string
  chunk_position: number
  chunk_count: number
  chunk_content: string | null
  material_item_id: string
  work_seq: number | null
  work_title: string | null
  author: string | null
  dimension_scores: Record<string, number>
  avg_score: number | null
  rated_at: string
}

export interface CrystalliseStatus {
  running: boolean
}

export type PluginIngestEvent =
  | { total: number }
  | { work: string; status: 'added' | 'updated' | 'unchanged'; added: number; updated: number; skipped: number }
  | { complete: true; added: number; updated: number; skipped: number }
  | { error: string }

export interface User {
  id: string
  email: string
  is_admin: boolean
  is_founding_admin?: boolean
  created_at?: string
  is_blocked?: boolean
  email_confirmed?: boolean
  force_password_change?: boolean
  daily_token_grant?: number | null
  token_grant_expiry_days?: number
  storage_limit_bytes?: number | null
}

export interface SiteSettings {
  default_storage_limit_mb: string
  default_daily_token_grant: string
  default_token_grant_expiry_days: string
  smtp_host: string
  smtp_port: string
  smtp_user: string
  smtp_password: string
  smtp_from: string
  smtp_use_tls: string
}

export interface TokenWindowStats {
  prompt: number
  completion: number
  total: number
}

export interface UsageSummary {
  balance: number | null
  today: TokenWindowStats
  week: TokenWindowStats
  month: TokenWindowStats
  all_time: TokenWindowStats
  by_project: { project_id: string; project_name?: string; all_time: TokenWindowStats }[]
}

export interface TokenGrant {
  id: string
  user_id: string
  amount: number
  granted_at: string
  expires_at: string | null
  granted_by: string
  note: string | null
}

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
  min_profile_confidence: number
  llm_model: string | null
  embedding_model: string | null
  created_at: string
  confidence?: number
  profile_confirmed_count?: number
  profile_confidence?: number | null
}

export interface ModelCatalogEntry {
  id: string
  source?: string
  type: 'llm' | 'embedding'
  domain: string
  enabled?: boolean
  is_default?: boolean
  display_name: string
  description: string
  parameter_size: string | null
  context_length: number | null
  size_bytes?: number | null
  quantization: string | null
  synced_at?: string | null
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
  domain: 'text' | 'image'
  position: number
  cluster_id: number | null
  description?: string | null
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
  prefilled_scores?: Record<string, number>
  ai_rating_id?: string | null
  ai_explanations?: Record<string, string>
}

export interface Rating {
  id: string
  project_id: string
  chunk_id: string
  material_item_id: string
  dimension_scores: Record<string, number>
  skipped: boolean
  skip_reason: string | null
  is_ai: boolean
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
  confirmed_count: number
  score_sum: number
  profile_confidence: number | null
  created_at: string
}

export interface PluginAction {
  name: string
  title: string
  description: string
  options_schema: Record<string, unknown>
}

export interface PluginInfo {
  name: string
  title: string
  description: string
  config_schema: Record<string, unknown>
  actions?: PluginAction[]
  supports_batched_ingest?: boolean
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
  content_is_image?: boolean
  storage_path: string | null
}

export interface ChunkRating {
  rating_id: string
  dimension_scores: Record<string, number>
  avg_score: number | null
  is_ai: boolean
  also_ai_rated?: boolean
  explanations: Record<string, string>
  rated_at: string
}

export interface WorkChunk {
  chunk_id: string
  material_item_id: string
  position: number
  chunk_count: number
  content: string | null
  domain: 'text' | 'image'
  description?: string | null
  rating: ChunkRating | null
}

export interface WritebackResult {
  updated: number
  skipped: number
  errors: string[]
}

export interface RatedChunkEntry {
  rating_id: string
  chunk_id: string
  chunk_position: number
  chunk_count: number
  chunk_content: string | null
  chunk_domain?: 'text' | 'image'
  chunk_description?: string | null
  material_item_id: string
  work_seq: number | null
  work_title: string | null
  author: string | null
  dimension_scores: Record<string, number>
  avg_score: number | null
  is_ai: boolean
  also_ai_rated?: boolean
  explanations: Record<string, string>
  rated_at: string
}

export interface WorkDimStat {
  avg: number
  max: number
  min: number
}

export interface WorkStats {
  total_chunks: number
  human_rated: number
  ai_rated: number
  overall_avg: number | null
  overall_max: number | null
  overall_min: number | null
  dim_stats: Record<string, WorkDimStat>
  first_description?: string | null
  chunk_descriptions?: { position: number; description: string }[]
}

export type MaterialItemWithStats = MaterialItem & WorkStats

export interface WorksListResponse {
  total: number
  items: MaterialItemWithStats[]
}

export interface AIRatingStatus {
  running: boolean
  profile_version: number | null
  profile_stale: boolean
  chunks_rated: number
  batches_completed: number
  last_batch_avg: number | null
  stopped_reason: 'diminishing_returns' | 'user_stopped' | 'complete' | 'error' | null
  tokens_prompt: number
  tokens_completion: number
}

export interface CrystalliseStatus {
  running: boolean
  tokens_prompt: number
  tokens_completion: number
}

export interface ProjectDefaults {
  default_crystallisation_threshold: number
  default_chunk_min_size: number
  default_chunk_max_size: number
  chunk_size_min_lower: number
  chunk_size_max_upper: number
}

export type PluginIngestEvent =
  | { total: number }
  | { work: string; status: 'added' | 'updated' | 'unchanged'; added: number; updated: number; skipped: number }
  | { complete: true; added: number; updated: number; skipped: number }
  | { error: string }

export type BatchIngestStatus =
  | { supported: false }
  | { supported: true; plugin: string; status: 'idle' | 'running' | 'paused' | 'done' | 'error'; fetched: number; total: number | null }

export type BatchIngestEvent =
  | { type: 'batch_start'; batch: number }
  | { type: 'item'; work: string; status: 'added' | 'updated' | 'unchanged'; batch_added: number; batch_updated: number; batch_unchanged: number }
  | { type: 'batch_done'; batch: number; added: number; updated: number; unchanged: number; total_added: number; total_updated: number; total_unchanged: number; total_fetched: number }
  | { type: 'pipeline_start'; batch: number }
  | { type: 'pipeline_phase'; phase: string; status: string; current?: number; total?: number }
  | { type: 'pipeline_done'; batch: number }
  | { type: 'complete'; batches: number; total_added: number; total_updated: number; total_unchanged: number; total_fetched: number }
  | { type: 'paused'; batch: number; total_fetched: number }
  | { type: 'error'; error: string }


export interface AppConfig {
  ai_preview_text: boolean
  ai_preview_image: boolean
}

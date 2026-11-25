/** 与后端 /api/v1 接口对应的数据类型。字段名保持与后端一致（snake_case）。 */

export type Role = 'analyst' | 'pr' | 'admin'
export type Level = 'S' | 'A' | 'B' | 'C'
export type Sentiment = '正向' | '中性' | '负向'
export type MediaType = 'text' | 'image' | 'video'

/** 后端统一错误格式 */
export interface ApiErrorBody {
  code: number
  message: string
  detail?: string
}

// ---------- 登录 ----------
export interface UserInfo {
  username: string
  role: Role
  display_name: string
}
export interface LoginResult extends UserInfo {
  token: string
}

// ---------- 虚拟时钟 / 演示 ----------
export interface ClockState {
  current_batch: number
  current_label: string
  current_time: string | null
  finished: boolean
  batches?: unknown[]
}
export interface BatchResult {
  batch: number
  label: string
  ingested: number
  filtered: number
  merged: string[]
  alert_ids: number[]
}
export interface AdvanceResult {
  current_batch: number
  current_label: string
  results: BatchResult[]
  message?: string
}

// ---------- 预警 ----------
export interface Alert {
  id: number
  event_id: string
  alert_type: string
  level: Level
  summary: string
  rule_desc: string
  triggered_at: string
  silence_until: string | null
  notified: string[]
  suppressed: number | boolean
  is_read: number | boolean
}

// ---------- 大盘 ----------
export interface Metrics {
  total: number
  merged: number
  filtered: number
  negative: number
  negative_rate: number
  active_events: number
  alerts: number
  unread_alerts: number
}
export interface TrendPoint {
  label: string
  time: string
  total: number
  negative: number
  positive: number
}
export interface WordItem {
  word: string
  count: number
}
export interface EventBrief {
  id: string
  title: string
  level: Level
  intensity_score: number
  status: string
  manual_override: number | boolean
}
export interface Overview {
  metrics: Metrics
  trend: TrendPoint[]
  sentiment: Record<Sentiment, number>
  words: WordItem[]
  events: EventBrief[]
  alerts: Alert[]
  clock: ClockState
}

// ---------- 内容 ----------
export interface Entity {
  name: string
  type: string
}
export interface ContentItem {
  id: string
  source_type: string
  platform: string
  author: string
  author_type?: string | null
  kol_weight: number
  published_at: string
  text: string
  ocr_text?: string | null
  asr_text?: string | null
  media_type: MediaType
  sentiment: Sentiment
  emotion?: string | null
  sensitive_hits: string[]
  entities?: Entity[]
  reposts: number
  comments: number
  likes: number
  interaction?: number
  dup_of?: string | null
  dup_count?: number
  event_id?: string | null
  event_level?: Level | null
  event_title?: string | null
}
export interface ContentBrief {
  id: string
  author: string
  platform?: string
  published_at: string
  text: string
}
export interface ContentDetail extends ContentItem {
  interaction: number
  parent_chain: ContentBrief[]
  merged_items: ContentBrief[]
}
export interface ContentQuery {
  topic_id?: number | string
  source_type?: string
  sentiment?: string
  emotion?: string
  level?: string
  event_id?: string
  media_type?: string
  start?: string
  end?: string
  keyword?: string
  include_dup?: boolean
  page?: number
  page_size?: number
}
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---------- 事件 ----------
export interface LevelAdjustment {
  created_at: string
  operator: string
  auto_level: Level
  auto_score: number
  new_level: Level | string
  reason: string
}
export interface SeriesPoint {
  label: string
  total: number
  negative: number
}
export interface ClusterQuote {
  id: string
  author: string
  text: string
}
export interface Cluster {
  id: number
  summary: string
  sentiment: Sentiment
  emotion: string | null
  count: number
  quotes: ClusterQuote[]
}
export interface Draft {
  id: number
  content: string
  gen_mode: string
  model_name: string | null
  created_by: string
  created_at: string
  adopted: number | boolean
  adopted_by: string | null
}
export interface EventDetail extends EventBrief {
  category?: string | null
  auto_level: Level
  auto_score: number
  content_count: number
  negative_count: number
  merged_count: number
  peak_volume: number
  first_content_id: string | null
  keywords: string[]
  score_speed: number
  score_interaction: number
  score_kol: number
  score_sensitive: number
  score_basis: Partial<Record<'speed' | 'interaction' | 'kol' | 'sensitive', string>>
  level_adjustments: LevelAdjustment[]
  series: SeriesPoint[]
  clusters: Cluster[]
  drafts: Draft[]
  alerts: Alert[]
  next_statuses: string[]
  llm_available: boolean
}
export interface TimelineNode {
  id: string
  published_at: string
  platform: string
  author: string
  kol_weight: number
  depth: number
  dup_count: number
  interaction: number
  text: string
  marks: string[]
}
export interface Timeline {
  nodes: TimelineNode[]
}
export interface GraphNode {
  id: string
  type: string
  count: number
  content_ids: string[]
}
export interface GraphEdge {
  source: string
  target: string
  weight: number
}
export interface EntityGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}
export interface Disposal {
  created_at: string
  from_status: string
  to_status: string
  operator: string
  role: Role | string
  note: string | null
}

// ---------- 报告 ----------
export interface ReportBrief {
  id: number
  event_id: string
  title: string
  level: Level
  gen_mode: string
  created_by: string
  created_at: string
}
export interface Report extends ReportBrief {
  markdown: string
}

// ---------- 主题 / 配置 ----------
export interface Topic {
  id: number
  name: string
  keywords: string[]
  channels: Record<string, boolean>
  enabled: number | boolean
  content_count: number
}
export interface TopicPayload {
  name: string
  keywords: string
  channels: Record<string, boolean>
  enabled: boolean
}
export interface MonitorConfig {
  surge_threshold: number
  surge_min_count: number
  kol_alert_weight: number
  silence_minutes: number
  level_s: number
  level_a: number
  level_b: number
  notify_site: boolean
  notify_email: boolean
  notify_sms: boolean
  llm_available: boolean
  llm_model: string
}

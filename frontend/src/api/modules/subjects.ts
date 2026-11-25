import { http, request } from '../http'
import { filenameFromDisposition } from '@/utils/download'

/** 主体风险等级（和舆情事件的 S/A/B/C 是两套口径） */
export type SubjectLevel = '高' | '中' | '低' | '无'

export interface SubjectBrief {
  rank: number
  subject_key: string
  credit_code?: string | null
  subject: string
  score: number
  level: SubjectLevel
  record_count: number
  fine_total: number
  worst_tier: string
  categories: Record<string, number>
  first_at?: string
  last_at: string
}

export interface SubjectRanking {
  source_id: string
  as_of: string
  category: string | null
  total: number
  subjects: SubjectBrief[]
}

export interface TopFine {
  id: number
  subject: string
  doc_no: string
  fine_amount: number
  category: string
  handling_result: string
  official_url: string
  published_at: string
}

export interface DistrictProfile {
  source_id: string
  as_of: string
  data_until: string | null
  record_count: number
  subject_count: number
  fined_count: number
  fine_total: number
  levels: Record<SubjectLevel, number>
  tiers: Record<string, number>
  by_category: Record<string, { records: number; fined: number; fine_total: number }>
  by_year: Record<string, { records: number; fine_total: number }>
  by_dept: Record<string, number>
  top_subjects: SubjectBrief[]
  top_fines: TopFine[]
}

export interface HealthReport {
  title: string
  subject_key: string
  as_of: string
  score: number
  level: SubjectLevel
  sections: { title: string; body: string }[]
}

export const subjectsApi = {
  profile: (as_of: string) =>
    request.get<DistrictProfile>('/subjects/profile', { params: { as_of, top: 5 } }),
  ranking: (as_of: string, category?: string) =>
    request.get<SubjectRanking>('/subjects/risk', {
      params: { as_of, category: category || undefined, limit: 50 },
    }),
  report: (key: string, as_of: string) =>
    request.get<HealthReport>(`/subjects/${encodeURIComponent(key)}/report`, { params: { as_of } }),
  async exportPdf(key: string, as_of: string): Promise<{ blob: Blob; filename: string }> {
    const res = await http.get<Blob>(`/subjects/${encodeURIComponent(key)}/report/export`, {
      params: { format: 'pdf', as_of },
      responseType: 'blob',
    })
    const header = res.headers['content-disposition'] as string | undefined
    return {
      blob: res.data,
      filename: filenameFromDisposition(header, `${key}_体检报告_${as_of}.pdf`),
    }
  },
}

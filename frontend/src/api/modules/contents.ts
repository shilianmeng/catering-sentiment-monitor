import { request } from '../http'
import type { ContentDetail, ContentItem, ContentQuery, Page } from '@/types'

/** 去掉空值，避免把空串当筛选条件发给后端 */
function clean(q: ContentQuery): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {}
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === '' || v === false) continue
    out[k] = typeof v === 'string' ? v.trim() : v
  }
  return out
}

export const contentsApi = {
  search: (q: ContentQuery) => request.get<Page<ContentItem>>('/contents', { params: clean(q) }),
  detail: (cid: string) => request.get<ContentDetail>(`/contents/${encodeURIComponent(cid)}`),
}

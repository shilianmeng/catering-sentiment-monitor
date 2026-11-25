import { request } from '../http'
import type { Alert, MonitorConfig, Topic, TopicPayload } from '@/types'

export const topicsApi = {
  list: () => request.get<Topic[]>('/topics'),
  create: (body: TopicPayload) => request.post<Topic>('/topics', body),
  update: (id: number, body: Partial<TopicPayload>) => request.put<Topic>(`/topics/${id}`, body),
  remove: (id: number) => request.delete<{ ok: boolean }>(`/topics/${id}`),
}

export type ConfigPayload = Partial<Omit<MonitorConfig, 'llm_available' | 'llm_model'>>

export const configApi = {
  get: () => request.get<MonitorConfig>('/config'),
  update: (body: ConfigPayload) => request.put<MonitorConfig>('/config', body),
}

export const alertsApi = {
  list: (eventId?: string) =>
    request.get<Alert[]>('/alerts', { params: eventId ? { event_id: eventId } : undefined }),
  markRead: (id: number) => request.put<Alert>(`/alerts/${id}/read`),
}

import { request } from '../http'
import type {
  Disposal,
  Draft,
  EntityGraph,
  EventBrief,
  EventDetail,
  Report,
  Timeline,
} from '@/types'

const base = (eid: string) => `/events/${encodeURIComponent(eid)}`

export const eventsApi = {
  list: () => request.get<EventBrief[]>('/events'),
  detail: (eid: string) => request.get<EventDetail>(base(eid)),
  timeline: (eid: string) => request.get<Timeline>(`${base(eid)}/timeline`),
  graph: (eid: string) => request.get<EntityGraph>(`${base(eid)}/graph`),
  changeLevel: (eid: string, level: string, reason: string) =>
    request.post<EventDetail>(`${base(eid)}/level`, { level, reason }),
  dispose: (eid: string, toStatus: string, note: string) =>
    request.post<EventDetail>(`${base(eid)}/disposal`, { to_status: toStatus, note }),
  disposals: (eid: string) => request.get<Disposal[]>(`${base(eid)}/disposals`),
  generateDraft: (eid: string) => request.post<Draft>(`${base(eid)}/response-draft`),
  adoptDraft: (eid: string, draftId?: number) =>
    request.post<Draft>(`${base(eid)}/draft-adopt`, draftId ? { draft_id: draftId } : {}),
  createReport: (eid: string) => request.post<Report>(`${base(eid)}/report`),
}

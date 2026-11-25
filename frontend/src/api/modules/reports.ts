import { http, request } from '../http'
import type { Report, ReportBrief } from '@/types'
import { filenameFromDisposition } from '@/utils/download'

export type ExportFormat = 'md' | 'pdf'

export const reportsApi = {
  list: () => request.get<ReportBrief[]>('/reports'),
  detail: (rid: number | string) => request.get<Report>(`/reports/${rid}`),
  async export(report: ReportBrief, format: ExportFormat): Promise<{ blob: Blob; filename: string }> {
    const res = await http.get<Blob>(`/reports/${report.id}/export`, {
      params: { format },
      responseType: 'blob',
    })
    const fallback = `report_${report.id}_${report.event_id}.${format}`
    const header = res.headers['content-disposition'] as string | undefined
    return { blob: res.data, filename: filenameFromDisposition(header, fallback) }
  },
}

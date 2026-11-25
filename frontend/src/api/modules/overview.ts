import { request } from '../http'
import type { AdvanceResult, ClockState, Overview } from '@/types'

export const overviewApi = {
  overview: () => request.get<Overview>('/overview'),
  clock: () => request.get<ClockState>('/clock', { silent: true }),
}

export const demoApi = {
  advance: (batches = 1) => request.post<AdvanceResult>('/demo/advance', { batches }),
  reset: () => request.post<AdvanceResult>('/demo/reset'),
}

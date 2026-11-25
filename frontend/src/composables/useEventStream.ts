/**
 * SSE 实时推送：组件挂载时连接 /api/v1/stream，卸载时断开。
 * EventSource 不能带请求头，所以用 ?token= 鉴权（后端只在这个接口接受 query token）。
 * 浏览器断线会自动重连；收到 batch_advanced 时顺带刷新顶部虚拟时钟。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { useClockStore } from '@/stores/clock'
import type { Alert, ClockState } from '@/types'
import { API_BASE } from '@/utils/constants'
import { authStorage } from '@/utils/storage'

export interface StreamHandlers {
  hello?: () => void
  batch_advanced?: (data: { clock: ClockState; label: string }) => void
  reset?: (data: { label: string }) => void
  alert_raised?: (data: Alert) => void
}

export type StreamStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export function useEventStream(handlers: StreamHandlers = {}) {
  const status = ref<StreamStatus>('connecting')
  const clockStore = useClockStore()
  let es: EventSource | null = null

  function parse<T>(e: MessageEvent): T {
    try {
      return JSON.parse((e.data as string) || '{}') as T
    } catch {
      return {} as T
    }
  }

  function open(): void {
    const token = authStorage.getToken()
    if (!token || typeof EventSource === 'undefined') {
      status.value = 'closed'
      return
    }
    es = new EventSource(`${API_BASE}/stream?token=${encodeURIComponent(token)}`)
    es.addEventListener('hello', () => {
      status.value = 'open'
      handlers.hello?.()
    })
    es.addEventListener('batch_advanced', (e) => {
      const data = parse<{ clock: ClockState; label: string }>(e as MessageEvent)
      clockStore.set(data.clock)
      handlers.batch_advanced?.(data)
    })
    es.addEventListener('reset', (e) => handlers.reset?.(parse(e as MessageEvent)))
    es.addEventListener('alert_raised', (e) => handlers.alert_raised?.(parse(e as MessageEvent)))
    es.onerror = () => {
      status.value = es?.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting'
    }
  }

  function close(): void {
    es?.close()
    es = null
    status.value = 'closed'
  }

  onMounted(open)
  onBeforeUnmount(close)

  return { status, close }
}

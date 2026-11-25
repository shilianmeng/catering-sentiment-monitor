import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { demoApi, overviewApi } from '@/api'
import type { AdvanceResult, ClockState } from '@/types'

/** 虚拟时钟与演示控制（推进 / 重置）。 */
export const useClockStore = defineStore('clock', () => {
  const clock = ref<ClockState | null>(null)
  const busy = ref(false)

  const text = computed(() => {
    const c = clock.value
    if (!c) return '虚拟时钟 -'
    const t = c.current_time ? c.current_time.slice(5) : '-'
    return `虚拟时钟 ${c.current_label} · ${t}${c.finished ? '（已到最后一批）' : ''}`
  })

  function set(c: ClockState | null | undefined): void {
    if (c) clock.value = c
  }

  async function refresh(): Promise<void> {
    try {
      set(await overviewApi.clock())
    } catch {
      /* 时钟拉取失败不打扰用户 */
    }
  }

  /** 推进一批，返回给用户看的提示语 */
  async function advance(): Promise<string> {
    busy.value = true
    try {
      const r: AdvanceResult = await demoApi.advance(1)
      await refresh()
      if (r.message) return r.message
      const x = r.results[0]
      if (!x) return `已推进到 ${r.current_label}`
      return `已推进到 ${x.label}：接入 ${x.ingested} 条，过滤 ${x.filtered} 条，合并水军帖 ${x.merged.length} 条`
    } finally {
      busy.value = false
    }
  }

  async function reset(): Promise<string> {
    busy.value = true
    try {
      await demoApi.reset()
      await refresh()
      return '已重置为预置演示数据（T0）'
    } finally {
      busy.value = false
    }
  }

  return { clock, busy, text, set, refresh, advance, reset }
})

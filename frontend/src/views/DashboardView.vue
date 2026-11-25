<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

import { overviewApi } from '@/api'
import AlertItem from '@/components/AlertItem.vue'
import LevelBadge from '@/components/LevelBadge.vue'
import LineChart from '@/components/LineChart.vue'
import WordCloud from '@/components/WordCloud.vue'
import { useEventStream } from '@/composables/useEventStream'
import { useClockStore } from '@/stores/clock'
import type { Alert, Overview } from '@/types'
import { COLORS } from '@/utils/constants'

const clock = useClockStore()
const data = ref<Overview | null>(null)
const loading = ref(false)
/** SSE 推来的新预警，置顶并闪烁，下次整体刷新时并入列表 */
const freshAlerts = ref<Alert[]>([])

async function load() {
  loading.value = true
  try {
    const d = await overviewApi.overview()
    data.value = d
    freshAlerts.value = []
    clock.set(d.clock)
  } finally {
    loading.value = false
  }
}

const { status } = useEventStream({
  batch_advanced: () => void load(),
  reset: () => void load(),
  alert_raised: (a) => {
    freshAlerts.value.unshift(a)
  },
})

const liveText = computed(
  () =>
    ({
      connecting: '● 实时推送连接中…',
      open: '● 实时推送已连接',
      reconnecting: '● 实时推送重连中…',
      closed: '● 实时推送未连接',
    })[status.value],
)

const metrics = computed(() => {
  const m = data.value?.metrics
  if (!m) return []
  return [
    { k: '总声量', v: m.total, s: `另合并水军近似帖 ${m.merged} 条、过滤不相关 ${m.filtered} 条` },
    { k: '负向率', v: `${m.negative_rate}%`, s: `负向 ${m.negative} 条` },
    { k: '活跃事件', v: m.active_events, s: '未结束处置的事件' },
    { k: '预警数', v: m.alerts, s: `未读 ${m.unread_alerts} 条` },
  ]
})

const trend = computed(() => {
  const t = data.value?.trend ?? []
  return {
    labels: t.map((x) => `${x.label} ${x.time}`),
    series: [
      { name: '总声量', data: t.map((x) => x.total), color: COLORS.primary },
      { name: '负向', data: t.map((x) => x.negative), color: COLORS.neg },
      { name: '正向', data: t.map((x) => x.positive), color: COLORS.pos },
    ],
  }
})

const donut = computed<EChartsOption>(() => {
  const s = data.value?.sentiment
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '45%'],
        label: { formatter: '{b}\n{d}%' },
        data: [
          { name: '正向', value: s?.['正向'] ?? 0, itemStyle: { color: COLORS.pos } },
          { name: '中性', value: s?.['中性'] ?? 0, itemStyle: { color: COLORS.neu } },
          { name: '负向', value: s?.['负向'] ?? 0, itemStyle: { color: COLORS.neg } },
        ],
      },
    ],
  }
})

onMounted(load)
</script>

<template>
  <div v-loading="loading && !data">
    <h2>
      态势大盘
      <span class="small live" :class="status">{{ liveText }}</span>
    </h2>

    <template v-if="data">
      <div class="grid g4">
        <div v-for="m in metrics" :key="m.k" class="card metric">
          <div class="k">{{ m.k }}</div>
          <div class="v">{{ m.v }}</div>
          <div class="small muted">{{ m.s }}</div>
        </div>
      </div>

      <div class="grid g3-1">
        <div>
          <div class="card">
            <h3>声量趋势（各批次新增条数）</h3>
            <LineChart :labels="trend.labels" :series="trend.series" />
          </div>
          <div class="grid g2">
            <div class="card">
              <h3>情感分布</h3>
              <VChart :option="donut" style="height: 230px" autoresize />
            </div>
            <div class="card">
              <h3>热点词云</h3>
              <WordCloud :words="data.words" />
            </div>
          </div>
          <div class="card">
            <h3>事件列表</h3>
            <table class="plain">
              <thead>
                <tr>
                  <th>等级</th>
                  <th>事件</th>
                  <th>烈度</th>
                  <th>处置状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="e in data.events" :key="e.id">
                  <td>
                    <LevelBadge :level="e.level" />
                    <span v-if="e.manual_override" class="tag manual">人工调整</span>
                  </td>
                  <td>
                    <RouterLink :to="`/events/${e.id}`">{{ e.title }}</RouterLink>
                    <span class="muted small"> {{ e.id }}</span>
                  </td>
                  <td>{{ e.intensity_score }}</td>
                  <td>{{ e.status }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="!data.events.length" class="empty">暂无事件</p>
          </div>
        </div>

        <div class="card">
          <h3>
            实时风险预警 <span class="tag">未读 {{ data.metrics.unread_alerts }}</span>
          </h3>
          <AlertItem v-for="a in freshAlerts" :key="`f${a.id}`" :alert="a" fresh />
          <AlertItem v-for="a in data.alerts" :key="a.id" :alert="a" />
          <p v-if="!data.alerts.length && !freshAlerts.length" class="empty">暂无预警</p>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.live {
  font-weight: normal;
  color: var(--muted);
  margin-left: 8px;
}
.live.open {
  color: var(--pos);
}
.metric .k {
  color: var(--muted);
}
.metric .v {
  font-size: 28px;
  font-weight: bold;
}
</style>

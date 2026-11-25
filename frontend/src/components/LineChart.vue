<script setup lang="ts">
/** 折线图（ECharts）：x 轴标签 + 若干条数据线。 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

export interface LineSeries {
  name: string
  data: number[]
  color: string
}

const props = withDefaults(defineProps<{ labels: string[]; series: LineSeries[]; height?: number }>(), {
  height: 260,
})

const option = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { top: 0 },
  grid: { left: 40, right: 16, top: 32, bottom: 28 },
  xAxis: { type: 'category', data: props.labels, boundaryGap: false },
  yAxis: { type: 'value', minInterval: 1 },
  series: props.series.map((s) => ({
    name: s.name,
    type: 'line',
    data: s.data,
    smooth: true,
    symbolSize: 6,
    itemStyle: { color: s.color },
    lineStyle: { color: s.color, width: 2 },
  })),
}))
</script>

<template>
  <VChart v-if="labels.length" :option="option" :style="{ height: `${height}px` }" autoresize />
  <p v-else class="empty">暂无数据</p>
</template>

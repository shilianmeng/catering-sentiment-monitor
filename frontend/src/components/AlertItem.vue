<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import type { Alert } from '@/types'
import { timeOnly } from '@/utils/format'
import LevelBadge from './LevelBadge.vue'

const props = defineProps<{ alert: Alert; fresh?: boolean }>()

const kind = computed(() =>
  props.alert.suppressed ? 'suppressed' : props.alert.alert_type === '升级' ? 'up' : '',
)
const channels = computed(() => (props.alert.notified || []).join('、') || '无')
</script>

<template>
  <div class="alert-item" :class="[kind, { fresh }]">
    <div class="row">
      <b>{{ alert.alert_type }}</b>
      <span v-if="alert.suppressed" class="tag">静默期内已抑制</span>
      <LevelBadge v-else :level="alert.level" />
      <span class="muted small">{{ alert.triggered_at }}（虚拟时间）</span>
      <span v-if="!alert.suppressed && !alert.is_read" class="tag neg">未读</span>
    </div>
    <div>{{ alert.summary }}</div>
    <div class="small muted">
      规则：{{ alert.rule_desc }}
      <template v-if="!alert.suppressed">
        ｜静默至 {{ timeOnly(alert.silence_until) }}｜已推送：{{ channels }}
      </template>
    </div>
    <div class="small">
      <RouterLink :to="`/events/${alert.event_id}`">查看事件 {{ alert.event_id }} →</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.alert-item {
  border-left: 4px solid var(--neg);
  padding: 6px 10px;
  margin-bottom: 8px;
  background: #fff8f7;
  border-radius: 4px;
}
.alert-item.suppressed {
  border-left-color: #bbb;
  background: #f6f6f6;
  color: var(--muted);
}
.alert-item.up {
  border-left-color: #8e44ad;
  background: #f7f1fb;
}
.alert-item.fresh {
  animation: flash 1.5s ease 2;
}
@keyframes flash {
  50% {
    background: #ffe1dc;
  }
}
</style>

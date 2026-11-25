<script setup lang="ts">
import { computed } from 'vue'

import type { WordItem } from '@/types'
import { WORD_COLORS } from '@/utils/constants'

const props = defineProps<{ words: WordItem[] }>()

const items = computed(() => {
  const counts = props.words.map((w) => w.count)
  const max = Math.max(...counts)
  const min = Math.min(...counts)
  return props.words.map((w, i) => {
    const size = 13 + (max === min ? 8 : ((w.count - min) / (max - min)) * 20)
    return {
      ...w,
      style: {
        fontSize: `${size.toFixed(0)}px`,
        color: WORD_COLORS[i % WORD_COLORS.length],
        fontWeight: size > 24 ? 'bold' : 'normal',
      },
    }
  })
})
</script>

<template>
  <div v-if="items.length" class="cloud">
    <span v-for="w in items" :key="w.word" :title="`${w.word}：${w.count} 次`" :style="w.style">
      {{ w.word }}
    </span>
  </div>
  <p v-else class="empty">暂无数据</p>
</template>

<style scoped>
.cloud {
  text-align: center;
  line-height: 2.1;
}
.cloud span {
  margin: 0 8px;
  display: inline-block;
}
</style>

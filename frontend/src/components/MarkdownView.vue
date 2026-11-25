<script setup lang="ts">
/**
 * 安全渲染报告 Markdown（renderMarkdown 内部已转义全部文本）。
 * 点击 [c001] 这类原文引用时抛出 cite 事件。
 */
import { computed } from 'vue'

import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ source: string | null | undefined }>()
const emit = defineEmits<{ cite: [contentId: string] }>()

const html = computed(() => renderMarkdown(props.source))

function onClick(e: MouseEvent) {
  const el = (e.target as HTMLElement | null)?.closest<HTMLElement>('a.cref')
  if (el?.dataset.id) {
    e.preventDefault()
    emit('cite', el.dataset.id)
  }
}
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- 内容已在 renderMarkdown 中完成 HTML 转义 -->
  <div class="md" @click="onClick" v-html="html" />
</template>

<style scoped>
.md :deep(h1),
.md :deep(h2) {
  font-size: 18px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 4px;
}
.md :deep(h3) {
  font-size: 15px;
  margin-top: 16px;
}
.md :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}
.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--line);
  padding: 4px 8px;
  text-align: left;
}
.md :deep(th) {
  background: #f7f9fc;
}
.md :deep(blockquote) {
  margin: 6px 0;
  padding: 4px 10px;
  border-left: 3px solid #c9d3e6;
  color: var(--muted);
}
.md :deep(code) {
  background: #f2f4f8;
  padding: 0 4px;
  border-radius: 3px;
}
.md :deep(a.ext) {
  word-break: break-all;
}
.md :deep(a.cref) {
  font-size: 12px;
}
</style>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ sentiment: string | null | undefined }>()

const cls = computed(() =>
  props.sentiment === '负向' ? 'neg' : props.sentiment === '正向' ? 'pos' : 'neu',
)
</script>

<template>
  <span class="tag" :class="cls">{{ sentiment }}</span>
</template>

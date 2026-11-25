<script setup lang="ts">
import type { Level } from '@/types'

defineProps<{ level: Level | string | null | undefined }>()
</script>

<template>
  <span v-if="level" class="lv" :class="`lv-${level}`">{{ level }}</span>
</template>

<style scoped>
.lv {
  display: inline-block;
  min-width: 24px;
  text-align: center;
  color: #fff;
  border-radius: 4px;
  font-weight: bold;
  padding: 0 6px;
  line-height: 20px;
}
.lv-S {
  background: var(--lv-s);
}
.lv-A {
  background: var(--lv-a);
}
.lv-B {
  background: var(--lv-b);
}
.lv-C {
  background: var(--lv-c);
}
</style>

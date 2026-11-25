<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppHeader from './AppHeader.vue'
</script>

<template>
  <div class="layout">
    <AppHeader />
    <main class="page">
      <RouterView v-slot="{ Component, route }">
        <!-- 事件专题切换事件时按 id 重建组件，保证数据和图表都刷新 -->
        <component :is="Component" :key="route.name === 'event' ? route.fullPath : route.name" />
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
</style>

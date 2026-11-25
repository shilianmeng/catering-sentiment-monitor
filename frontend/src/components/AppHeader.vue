<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useAuthStore } from '@/stores/auth'
import { useClockStore } from '@/stores/clock'
import { APP_TITLE, DEFAULT_EVENT_ID } from '@/utils/constants'

const auth = useAuthStore()
const clock = useClockStore()
const route = useRoute()
const router = useRouter()

const links = [
  { to: '/', name: 'dashboard', label: '态势大盘' },
  { to: '/workbench', name: 'workbench', label: '研判工作台' },
  { to: `/events/${DEFAULT_EVENT_ID}`, name: 'event', label: '事件专题' },
  { to: '/reports', name: 'reports', label: '报告中心' },
  { to: '/subjects', name: 'subjects', label: '主体风险' },
  { to: '/settings', name: 'settings', label: '监测配置' },
]

const isAdmin = computed(() => auth.hasRole('admin'))

async function onAdvance() {
  try {
    ElMessage.success(await clock.advance())
  } catch {
    /* 错误已由请求拦截器提示 */
  }
}

async function onReset() {
  try {
    await ElMessageBox.confirm('将清空当前演示的报告、预警及处置记录，并恢复 T0 数据。确定重置？', '重置演示', { type: 'warning' })
  } catch {
    return
  }
  try {
    ElMessage.success(await clock.reset())
  } catch {
    /* 错误已由请求拦截器提示 */
  }
}

async function onLogout() {
  await auth.logout()
  await router.replace({ name: 'login' })
}

onMounted(() => clock.refresh())
</script>

<template>
  <header class="topbar">
    <span class="brand">{{ APP_TITLE }}</span>
    <nav>
      <RouterLink
        v-for="l in links"
        :key="l.name"
        :to="l.to"
        :class="{ active: route.name === l.name }"
      >
        {{ l.label }}
      </RouterLink>
    </nav>
    <span class="spacer" />
    <span class="clock" title="虚拟时钟">{{ clock.text }}</span>
    <template v-if="isAdmin">
      <button :disabled="clock.busy" title="接入下一批模拟数据" @click="onAdvance">推进时钟 ▶</button>
      <button :disabled="clock.busy" title="删库重建演示数据" @click="onReset">重置演示</button>
    </template>
    <span class="user">{{ auth.user?.display_name }}（{{ auth.roleName }}）</span>
    <button @click="onLogout">退出</button>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 18px;
  background: #18233a;
  color: #fff;
  padding: 0 20px;
  height: var(--header-h);
  position: sticky;
  top: 0;
  z-index: 20;
}
.brand {
  font-weight: bold;
  font-size: 16px;
  white-space: nowrap;
}
nav a {
  color: #c9d3e6;
  padding: 15px 10px;
  display: inline-block;
}
nav a.active {
  color: #fff;
  border-bottom: 3px solid #5b9bff;
}
.clock {
  background: #26355a;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 13px;
  white-space: nowrap;
}
button {
  font: inherit;
  cursor: pointer;
  background: #26355a;
  color: #fff;
  border: 1px solid #3a4c78;
  border-radius: 6px;
  padding: 3px 10px;
  white-space: nowrap;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.user {
  font-size: 13px;
  color: #c9d3e6;
  white-space: nowrap;
}
</style>

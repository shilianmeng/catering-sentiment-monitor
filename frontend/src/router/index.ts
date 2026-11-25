import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { APP_TITLE, DEFAULT_EVENT_ID } from '@/utils/constants'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    /** 不需要登录即可访问 */
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '态势大盘' },
      },
      {
        path: 'workbench',
        name: 'workbench',
        component: () => import('@/views/WorkbenchView.vue'),
        meta: { title: '研判工作台' },
      },
      { path: 'events', redirect: `/events/${DEFAULT_EVENT_ID}` },
      {
        path: 'events/:id',
        name: 'event',
        component: () => import('@/views/EventDetailView.vue'),
        props: true,
        meta: { title: '事件专题' },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/ReportsView.vue'),
        meta: { title: '报告中心' },
      },
      {
        path: 'subjects',
        name: 'subjects',
        component: () => import('@/views/SubjectsView.vue'),
        meta: { title: '主体风险' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '监测配置' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在', public: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { name: 'login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : undefined }
  }
  if (to.name === 'login' && auth.isLoggedIn) return { name: 'dashboard' }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ${APP_TITLE}` : APP_TITLE
})

export default router

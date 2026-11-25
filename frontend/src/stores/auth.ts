import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '@/api'
import type { Role, UserInfo } from '@/types'
import { ROLE_NAME } from '@/utils/constants'
import { authStorage } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(authStorage.getToken())
  const user = ref<UserInfo | null>(authStorage.getUser())

  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const role = computed<Role | null>(() => user.value?.role ?? null)
  const roleName = computed(() => (role.value ? ROLE_NAME[role.value] : ''))

  function hasRole(...roles: Role[]): boolean {
    return !!role.value && roles.includes(role.value)
  }

  async function login(username: string, password: string): Promise<void> {
    const res = await authApi.login(username.trim(), password)
    const info: UserInfo = { username: res.username, role: res.role, display_name: res.display_name }
    authStorage.save(res.token, info)
    token.value = res.token
    user.value = info
  }

  /** 只清本地状态（401 时用） */
  function clear(): void {
    authStorage.clear()
    token.value = null
    user.value = null
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      /* token 已失效也照样退出 */
    }
    clear()
  }

  return { token, user, isLoggedIn, role, roleName, hasRole, login, logout, clear }
})

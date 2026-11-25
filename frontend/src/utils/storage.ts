import type { UserInfo } from '@/types'
import { STORAGE_TOKEN, STORAGE_USER } from './constants'

/** 登录态持久化（localStorage）。集中在这里，方便以后换成 cookie 等方案。 */
export const authStorage = {
  getToken(): string | null {
    return localStorage.getItem(STORAGE_TOKEN)
  },
  getUser(): UserInfo | null {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_USER) || 'null') as UserInfo | null
    } catch {
      return null
    }
  },
  save(token: string, user: UserInfo): void {
    localStorage.setItem(STORAGE_TOKEN, token)
    localStorage.setItem(STORAGE_USER, JSON.stringify(user))
  },
  clear(): void {
    localStorage.removeItem(STORAGE_TOKEN)
    localStorage.removeItem(STORAGE_USER)
  },
}

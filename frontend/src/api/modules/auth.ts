import { request } from '../http'
import type { LoginResult, UserInfo } from '@/types'

export const authApi = {
  login: (username: string, password: string) =>
    request.post<LoginResult>('/login', { username, password }, { silent: true }),
  logout: () => request.post<{ ok: boolean }>('/logout', undefined, { silent: true }),
  me: () => request.get<UserInfo>('/me'),
}

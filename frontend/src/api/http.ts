/**
 * Axios 实例与拦截器：
 * - 请求自动带 Bearer token；
 * - 后端统一错误格式 {code, message, detail} 转成 ApiError；
 * - 401 清除登录态并跳转登录页；
 * - 默认弹出错误提示，调用方可传 silent: true 自行处理。
 */
import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

import type { ApiErrorBody } from '@/types'
import { API_BASE } from '@/utils/constants'
import { authStorage } from '@/utils/storage'

declare module 'axios' {
  interface AxiosRequestConfig {
    /** 为 true 时出错不弹全局提示 */
    silent?: boolean
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** 401 时的回调，由 main.ts 注入（避免 http 层直接依赖 router / store） */
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 60_000,
})

http.interceptors.request.use((config) => {
  const token = authStorage.getToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

async function messageOf(err: AxiosError): Promise<string> {
  const data = err.response?.data as unknown
  if (data instanceof Blob) {
    // responseType: 'blob' 时错误体也是 Blob，需要再解析一次
    try {
      const body = JSON.parse(await data.text()) as ApiErrorBody
      return body.message || body.detail || '请求失败'
    } catch {
      return `请求失败（${err.response?.status ?? '网络错误'}）`
    }
  }
  if (data && typeof data === 'object') {
    const body = data as Partial<ApiErrorBody>
    if (body.message || body.detail) return String(body.message || body.detail)
  }
  if (err.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (!err.response) return '无法连接后端服务，请确认后端已启动（端口 8091）'
  return `请求失败（${err.response.status}）`
}

http.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const status = err.response?.status ?? 0
    const message = await messageOf(err)
    const cfg = (err.config ?? {}) as AxiosRequestConfig
    const isLogin = (cfg.url ?? '').endsWith('/login')
    if (status === 401 && !isLogin) {
      authStorage.clear()
      onUnauthorized?.()
    } else if (!cfg.silent) {
      ElMessage.error(message)
    }
    return Promise.reject(new ApiError(message, status))
  },
)

/** 只取 data 的便捷方法 */
export const request = {
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    http.get<T>(url, config).then((r) => r.data),
  post: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    http.post<T>(url, body, config).then((r) => r.data),
  put: <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
    http.put<T>(url, body, config).then((r) => r.data),
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    http.delete<T>(url, config).then((r) => r.data),
}

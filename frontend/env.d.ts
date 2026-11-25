/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 接口前缀，默认 /api/v1（开发时由 Vite 代理到后端，生产由 Nginx 反代） */
  readonly VITE_API_BASE: string
  /** 应用标题 */
  readonly VITE_APP_TITLE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

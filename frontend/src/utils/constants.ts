import type { Level, Role } from '@/types'

export const APP_TITLE = import.meta.env.VITE_APP_TITLE || '餐饮舆情监测与研判'
export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export const STORAGE_TOKEN = 'yq_token'
export const STORAGE_USER = 'yq_user'

export const ROLE_NAME: Record<Role, string> = { analyst: '分析师', pr: '公关', admin: '管理员' }

export const LEVELS: Level[] = ['S', 'A', 'B', 'C']
export const SOURCE_TYPES = ['社交媒体', '新闻门户', '短视频平台', '行业论坛']
export const SENTIMENTS = ['负向', '中性', '正向']
export const EMOTIONS = ['愤怒', '失望', '恐慌', '质疑']
export const MEDIA_NAME: Record<string, string> = { text: '文字', image: '图片', video: '视频' }
export const STATUS_FLOW = ['待处理', '跟踪中', '已核实', '已处理 / 辟谣处理']
export const TERMINAL_STATUSES = ['已处理', '辟谣处理', '忽略']

export const COLORS = {
  primary: '#2f6fde',
  neg: '#d64541',
  pos: '#2e9e5b',
  neu: '#8a94a6',
} as const

export const LEVEL_COLOR: Record<Level, string> = {
  S: '#c0392b',
  A: '#e67e22',
  B: '#d4ac0d',
  C: '#7f8c8d',
}

export const ENTITY_COLOR: Record<string, string> = {
  机构: '#2f6fde',
  人物: '#8e44ad',
  产品: '#e67e22',
  事件: '#d64541',
}

export const WORD_COLORS = [
  '#d64541',
  '#2f6fde',
  '#e67e22',
  '#8e44ad',
  '#2e9e5b',
  '#16a085',
  '#c0392b',
]

/** 事件专题页的默认事件（导航栏「事件专题」入口） */
export const DEFAULT_EVENT_ID = 'ev001'

/**
 * 主体风险页的默认评估日期。分数按处罚距评估日的时间衰减，不固定的话演示数字会一天天变；
 * 后端不填 as_of 仍按当天算，这里只是演示入口的默认值，页面上可以改。
 */
export const SUBJECT_DEMO_AS_OF = '2026-11-23'
export const SUBJECT_FOOD_CATEGORY = '食品安全'

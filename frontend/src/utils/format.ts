export interface TextSegment {
  text: string
  hit: boolean
}

/** 把文本按关键词切成片段，供模板用 <mark> 高亮（不使用 v-html，避免 XSS）。 */
export function splitHighlight(text: string | null | undefined, keyword?: string | null): TextSegment[] {
  const src = String(text ?? '')
  const kw = (keyword ?? '').trim()
  if (!kw || !src) return [{ text: src, hit: false }]
  const out: TextSegment[] = []
  let from = 0
  let idx = src.indexOf(kw)
  while (idx !== -1) {
    if (idx > from) out.push({ text: src.slice(from, idx), hit: false })
    out.push({ text: kw, hit: true })
    from = idx + kw.length
    idx = src.indexOf(kw, from)
  }
  if (from < src.length) out.push({ text: src.slice(from), hit: false })
  return out
}

/** "2026-03-01 10:20:00" → "03-01 10:20:00" */
export function shortTime(s: string | null | undefined): string {
  return s ? s.slice(5) : '-'
}

/** "2026-03-01 10:20:00" → "10:20:00" */
export function timeOnly(s: string | null | undefined): string {
  return s ? s.slice(11) : ''
}

export function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

export function formatNumber(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString('zh-CN')
}

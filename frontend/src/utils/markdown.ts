/**
 * 极简 Markdown 渲染：标题 / 列表 / 表格 / 粗体 / 行内代码 / 引用 / 裸 http(s) 网址（新窗口打开）。
 * 所有文本先做 HTML 转义再拼标签，输出可安全用于 v-html。
 * 报告中的 [c001] 形式的原文引用渲染为 <a class="cref" data-id="c001">，由 MarkdownView 统一处理点击。
 */

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c] ?? c)
}

/**
 * 裸露的 http(s) 网址（在已转义文本上匹配）。只认 http/https，javascript: 等协议不会被链接化；
 * 遇到空白、转义后的 < > " '、反引号、星号或中文标点即结束，末尾的英文标点不算网址。
 * 转义后的 &amp; 留在 href 里，浏览器会还原成 &，查询串不受影响。
 */
const BARE_URL = /https?:\/\/(?:(?!&(?:lt|gt|quot|#39);)[^\s`*<>"'，。；！？、）】」《》])+/g

function linkify(escaped: string): string {
  return escaped.replace(BARE_URL, (m) => {
    const url = m.replace(/[.,;:!?)\]]+$/, '')
    const tail = m.slice(url.length)
    return `<a href="${url}" class="ext" target="_blank" rel="noopener noreferrer">${url}</a>${tail}`
  })
}

function inline(s: string): string {
  return linkify(escapeHtml(s))
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\[(c\d{3,})\]/g, '<a href="javascript:void(0)" class="cref" data-id="$1">[$1]</a>')
}

const TABLE_ROW = /^\s*\|/
const TABLE_SEP = /^\s*\|[\s\-:|]+\|\s*$/
const LIST_ITEM = /^\s*([-*]|\d+\.)\s/
const HEADING = /^(#{1,4})\s/

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((c) => c.trim())
}

export function renderMarkdown(md: string | null | undefined): string {
  const lines = String(md ?? '').split(/\r?\n/)
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''
    if (TABLE_ROW.test(line)) {
      const rows: string[] = []
      while (i < lines.length && TABLE_ROW.test(lines[i] ?? '')) rows.push(lines[i++] ?? '')
      const body = rows.filter((r) => !TABLE_SEP.test(r))
      const html = body
        .map((r, k) => {
          const tag = k === 0 ? 'th' : 'td'
          return '<tr>' + cells(r).map((c) => `<${tag}>${inline(c)}</${tag}>`).join('') + '</tr>'
        })
        .join('')
      out.push(`<table>${html}</table>`)
      continue
    }
    const h = HEADING.exec(line)
    if (h) {
      const n = h[1]!.length
      out.push(`<h${n}>${inline(line.replace(/^#+\s*/, ''))}</h${n}>`)
      i++
      continue
    }
    if (LIST_ITEM.test(line)) {
      const items: string[] = []
      while (i < lines.length && LIST_ITEM.test(lines[i] ?? '')) {
        items.push((lines[i++] ?? '').replace(LIST_ITEM, ''))
      }
      out.push('<ul>' + items.map((x) => `<li>${inline(x)}</li>`).join('') + '</ul>')
      continue
    }
    if (/^>\s?/.test(line)) {
      out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`)
      i++
      continue
    }
    if (line.trim()) out.push(`<p>${inline(line)}</p>`)
    i++
  }
  return out.join('\n')
}

import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../markdown'
import { splitHighlight } from '../format'

describe('untrusted content rendering', () => {
  it('escapes executable HTML while preserving report citations', () => {
    const host = document.createElement('div')
    host.innerHTML = renderMarkdown('<img src=x onerror=alert(1)> **note** [c001]')
    expect(host.querySelector('img')).toBeNull()
    expect(host.querySelector('b')?.textContent).toBe('note')
    expect(host.querySelector('.cref')?.getAttribute('data-id')).toBe('c001')
  })
  it('handles empty reports and table separators', () => {
    expect(renderMarkdown(null)).toBe('')
    const host = document.createElement('div')
    host.innerHTML = renderMarkdown('| Name | Count |\n| --- | --- |\n| Example | 2 |')
    expect(host.querySelectorAll('tr')).toHaveLength(2)
  })
  it('links bare http(s) source URLs safely', () => {
    const url =
      'https://www.yuexiu.gov.cn/xyyxzl/credit/sgshzPunish/detail?sGuid=18c81849-0568-11f1-86f8-3b49921c58d2&a=1'
    const host = document.createElement('div')
    host.innerHTML = renderMarkdown(`- 原文：${url}。\n- 见 **${url}**`)
    const links = host.querySelectorAll<HTMLAnchorElement>('a.ext')
    expect(links).toHaveLength(2)
    expect(links[0]!.getAttribute('href')).toBe(url)
    expect(links[0]!.textContent).toBe(url)
    expect(links[0]!.getAttribute('target')).toBe('_blank')
    expect(links[0]!.getAttribute('rel')).toBe('noopener noreferrer')
    expect(links[0]!.parentElement?.textContent).toBe(`原文：${url}。`)
    expect(links[1]!.closest('b')).not.toBeNull()
  })
  it('does not link non-http schemes or let URLs break out of attributes', () => {
    const host = document.createElement('div')
    host.innerHTML = renderMarkdown(
      'javascript:alert(1) data:text/html,x https://e.com/"onmouseover="alert(1) https://e.com/a).',
    )
    const links = host.querySelectorAll<HTMLAnchorElement>('a')
    expect(links).toHaveLength(2)
    expect(links[0]!.getAttribute('href')).toBe('https://e.com/')
    expect(links[0]!.getAttribute('onmouseover')).toBeNull()
    expect(links[1]!.getAttribute('href')).toBe('https://e.com/a')
  })
  it('treats filter keywords literally, including regex and HTML characters', () => {
    expect(splitHighlight('a.*b.*', '.*')).toEqual([
      { text: 'a', hit: false }, { text: '.*', hit: true },
      { text: 'b', hit: false }, { text: '.*', hit: true },
    ])
    expect(splitHighlight('<img>', '')).toEqual([{ text: '<img>', hit: false }])
  })
})

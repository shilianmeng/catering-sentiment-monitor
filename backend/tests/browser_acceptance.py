"""Optional browser acceptance: python -m tests.browser_acceptance (requires Playwright + Edge)."""
import json
import os
import runpy
import sys
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.request

import uvicorn
from playwright.sync_api import sync_playwright

import tests  # Initialize the isolated database even when discovery omits -t .

from app.main import app
from app.core import config

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'screenshots' / 'vue'
OUT.mkdir(exist_ok=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    backend_port, frontend_port = free_port(), free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=backend_port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    env = dict(os.environ, VITE_BACKEND_ORIGIN=f'http://127.0.0.1:{backend_port}')
    log = (OUT / 'vite.log').open('w', encoding='utf-8')
    front = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', 'preview', '--port', str(frontend_port)],
                             cwd=ROOT / 'frontend', env=env, stdout=log, stderr=log)
    base = f'http://127.0.0.1:{frontend_port}'
    result = {'screenshots': [], 'errors': [], 'checks': []}
    try:
        for _ in range(150):
            try:
                if server.started:
                    urllib.request.urlopen(base, timeout=1).close()
                    break
            except OSError:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('Services did not become ready')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True, args=['--no-proxy-server'])
            page = browser.new_page(viewport={'width': 1600, 'height': 1000})
            page.on('pageerror', lambda e: result['errors'].append(str(e)))
            page.on('console', lambda m: result['errors'].append(m.text) if m.type == 'error' else None)
            page.on('response', lambda r: print('HTTP', r.status, r.url.split('?')[0], flush=True) if r.status >= 400 else None)

            def shot(name):
                page.locator('.el-message').last.wait_for(state='hidden', timeout=10000)
                page.wait_for_timeout(1000)
                page.screenshot(path=str(OUT / f'{name}.png'), full_page=True)
                result['screenshots'].append(name)
                print('SCREEN', name, flush=True)

            def go(path):
                page.goto(base + path)
                page.locator('main').wait_for()
                page.wait_for_timeout(700)

            def api(path, body=None):
                return page.evaluate('''async ([path, body]) => {
                  const token = Object.entries(localStorage).find(([k]) => k.includes('token'))?.[1];
                  const r = await fetch('/api/v1' + path, {method: body === null ? 'GET' : 'POST',
                    headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                    ...(body === null ? {} : {body: JSON.stringify(body)})});
                  if (!r.ok) throw new Error('API ' + path + ': ' + r.status);
                  return r.json();
                }''', [path, body])

            def login(user):
                page.goto(base + '/login')
                page.get_by_placeholder('用户名').fill(user)
                page.get_by_placeholder('密码', exact=True).fill('123456')
                page.locator('button[type=submit]').click()
                page.wait_for_url(base + '/')
                page.get_by_text('总声量', exact=True).wait_for()

            page.goto(base + '/login')
            page.get_by_placeholder('用户名').wait_for()
            shot('01_login')
            login('admin')
            page.get_by_text('● 实时推送已连接', exact=True).wait_for()
            shot('02_dashboard_T0')
            page.reload()
            page.get_by_text('● 实时推送已连接', exact=True).wait_for()
            assert page.url == base + '/'
            result['checks'].append('登录后刷新保留会话')
            page.get_by_role('button', name='推进时钟').click()
            page.wait_for_function("document.querySelector('.clock').textContent.includes('T1')")
            result['checks'].append('SSE advance T1')
            shot('03_dashboard_T1')
            api('/demo/advance', {'batches': 6})
            page.wait_for_function("document.querySelector('.clock').textContent.includes('T6')")
            shot('04_dashboard_T6')
            overview = api('/overview')
            assert overview['metrics']['total'] == 73
            assert overview['metrics']['negative_rate'] == 76.7
            event = api('/events/ev001')
            assert event['content_count'] == 69
            assert round(100 * event['negative_count'] / event['content_count'], 1) == 81.2
            assert event['intensity_score'] == 96 and event['level'] == 'S'
            result['checks'].append('T6 大盘 73/76.7%，ev001 69/81.2%/S96（改级前）')
            go('/settings')
            page.get_by_role('button', name='新增主题').wait_for()
            shot('05_settings')
            go('/workbench')
            page.locator('.ccard').first.wait_for()
            shot('06_workbench')
            page.get_by_placeholder('关键词（正文/OCR/ASR/作者）').fill('退款')
            page.get_by_role('button', name='查询', exact=True).click()
            page.locator('mark').first.wait_for()
            shot('07_filter')
            items = api('/contents?page_size=200')['items']
            for field in ('ocr_text', 'asr_text'):
                item = next(x for x in items if x.get(field))
                go('/workbench?cid=' + item['id'])
                page.locator('.el-drawer').wait_for()
                shot('08_' + field)
            go('/events/ev001')
            page.get_by_text('烈度评分（四项各 0–25 分）', exact=True).wait_for()
            shot('09_event')
            for title, name in [('传播时间线', '09_timeline'), ('实体关系图谱', '09_graph'), ('观点聚类', '09_clusters')]:
                page.locator('.card').filter(has=page.get_by_role('heading', name=title, exact=False)).screenshot(path=str(OUT / f'{name}.png'))
                result['screenshots'].append(name)
            api('/events/ev001/level', {'level': 'A', 'reason': 'Vue acceptance'})
            api('/events/ev001/disposal', {'to_status': '跟踪中', 'note': 'Vue acceptance'})
            go('/events/ev001')
            shot('10_audit_trail')
            page.get_by_role('button', name='生成草案', exact=True).click()
            page.get_by_text('模板生成', exact=True).first.wait_for()
            shot('11_draft_template')
            page.get_by_role('button', name='生成研判报告', exact=True).click()
            page.wait_for_url('**/reports?id=*')
            page.locator('.md').wait_for()
            shot('12_report_template')
            for label, extension in [('导出 Markdown', '.md'), ('导出 PDF', '.pdf')]:
                with page.expect_download() as pending:
                    page.get_by_role('button', name=label, exact=True).click()
                download = pending.value
                download.save_as(str(OUT / ('report' + extension)))
                assert (OUT / ('report' + extension)).stat().st_size > 100
                result['checks'].append(label)
            if '--real-model' in sys.argv:
                # Explicit opt-in only; keep ordinary acceptance deterministic and free of model calls.
                prior = os.environ.pop('OPENAI_API_KEY', None)
                try:
                    config.OPENAI_API_KEY = runpy.run_path(config.__file__)['OPENAI_API_KEY']
                finally:
                    if prior is not None:
                        os.environ['OPENAI_API_KEY'] = prior
                assert config.OPENAI_API_KEY, 'Real-model acceptance requires a configured key'
                go('/events/ev001')
                page.get_by_role('button', name='生成草案', exact=True).click()
                page.get_by_text('模型生成', exact=True).first.wait_for(timeout=120000)
                shot('11_draft_model')
                page.get_by_role('button', name='生成研判报告', exact=True).click()
                page.wait_for_url('**/reports?id=*', timeout=120000)
                page.locator('.md').wait_for()
                page.get_by_text('模型生成', exact=True).first.wait_for()
                shot('12_report_model')
                for label, extension in [('导出 Markdown', '.md'), ('导出 PDF', '.pdf')]:
                    with page.expect_download() as pending:
                        page.get_by_role('button', name=label, exact=True).click()
                    pending.value.save_as(str(OUT / ('report-model' + extension)))
                result['checks'].append('真实模型话术、报告及双格式导出')
                config.OPENAI_API_KEY = ''
            for user in ('analyst', 'pr'):
                page.get_by_role('button', name='退出', exact=True).click()
                page.wait_for_url(base + '/login')
                page.goto(base + '/settings')
                page.wait_for_url(lambda url: '/login?redirect=' in url)
                result['checks'].append('退出后受保护页面重定向 ' + user)
                login(user)
                assert page.get_by_role('button', name='推进时钟').count() == 0
                go('/events/ev001')
                assert page.get_by_role('button', name='生成研判报告', exact=True).count() == (1 if user == 'analyst' else 0)
                shot('13_role_' + user)
                result['checks'].append('role ' + user)
            page.goto(base + '/unknown-page')
            page.get_by_text('404', exact=False).first.wait_for()
            shot('14_not_found')
            browser.close()
        assert not result['errors'], result['errors']
        result['passed'] = True
    finally:
        front.terminate()
        front.wait(timeout=10)
        log.close()
        server.should_exit = True
        thread.join(timeout=10)
        (OUT / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()

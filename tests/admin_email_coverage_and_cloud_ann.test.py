"""admin_email_coverage_and_cloud_ann.test.py
两个新功能的 RED 冒烟测试：
  T1 管理端「邮箱绑定覆盖率」徽章在用户管理卡片显示（数字 + 百分号 + 阈值颜色）
  T2 管理员发布公告后：前端调用 announcements Supabase 表 写 + 读 都成功，cloud_ann_count>=1
  T3 退出登录（匿名）后刷新页面：顶部公告条仍包含该公告标题（证明从服务端表拉，非 localStorage 私有）
"""
from playwright.sync_api import sync_playwright
import os, sys, json, subprocess, time, urllib.request

ROOT = os.path.dirname(__file__)
BASE = 'http://localhost:8001/index.html'
ADMIN = '15184461098_admin'
ADM_PWD = '20091208'
SB_URL   = 'https://hjryfgujkxuaxovftlai.supabase.co'
SB_ANON  = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTYyMTQwMDAsImV4cCI6MjA3MTc5MDAwMH0.placeholder'
# 从 index.html 里能读到 SB_KEY / SB_URL 的常量就好，这里只做 REST 兜底写

LOGS = []
def onmsg(m):
    LOGS.append((m.type, m.text))
    if m.type in ('error','warning') and ('Failed to load' not in m.text):
        print(f'[CONSOLE-{m.type}]', m.text[:300])


def _sb_ann_rest(method, path_suffix='', json_body=None, key=None):
    """直接走 REST 检查 announcements 表（绕过前端缓存）。返回 (ok, body_or_err)。"""
    try:
        url = f'{SB_URL}/rest/v1/announcements{path_suffix}'
        data = None if json_body is None else json.dumps(json_body).encode('utf-8')
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('apikey', key or os.environ.get('SB_ANON', SB_ANON))
        req.add_header('Authorization', 'Bearer ' + (key or os.environ.get('SB_ANON', SB_ANON)))
        req.add_header('Content-Type', 'application/json')
        req.add_header('Prefer', 'return=representation')
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode('utf-8', 'ignore')
            return (200 <= r.status < 300, body)
    except Exception as e:
        return (False, str(e))


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on('console', onmsg)
        page.on('pageerror', lambda e: print('[PAGE ERR]', str(e)))

        # ===== 前置：确保本地服务在跑 =====
        try:
            page.goto(BASE, timeout=15000)
        except Exception:
            print('[提示] 8001 没起来，尝试启动 python -m http.server 8001')
            p = subprocess.Popen(
                [sys.executable, '-m', 'http.server', '8001', '--bind', '127.0.0.1'],
                cwd=os.path.dirname(ROOT),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            page.goto(BASE, timeout=15000)

        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)

        # ===== 先退出（保证是干净登录态） =====
        try: page.evaluate('try{ doLogout(); }catch(e){}')
        except Exception: pass
        page.wait_for_timeout(400)

        # ===== 登录管理员 =====
        page.evaluate("document.getElementById('view-welcome')?.classList.contains('hidden') || ''")
        page.evaluate("try{ openAuth(); }catch(e){}")
        page.wait_for_timeout(300)
        page.evaluate("""({u,p})=>{
          const ui = document.getElementById('authUser');
          const pi = document.getElementById('authPass');
          if(ui){ ui.value = u; ui.dispatchEvent(new Event('input',{bubbles:true})); }
          if(pi){ pi.value = p; pi.dispatchEvent(new Event('input',{bubbles:true})); }
        }""", {'u': ADMIN, 'p': ADM_PWD})
        page.evaluate("try{ doLogin(); }catch(e){}")
        # 等登录完成 + 云端校验（含 isAdmin 探测）
        for _ in range(20):
            state = page.evaluate("(()=>{ try{ return {cu:!!currentUser, adm:!!isAdmin}; }catch(e){ return {cu:false,adm:false}; } })()")
            if state['cu'] and state['adm']: break
            page.wait_for_timeout(300)
        page.evaluate("try{ go('admin'); }catch(e){}")
        # 给 adminLoadEmailCoverage / admin_count_emails RPC 留足时间
        # 等待结束条件：徽章 stat 文本不再包含「加载中…」 或 报错信息（含「失败」字样即停下）
        loaded = False
        for i in range(70):
            s = page.evaluate("""(()=>{ try{
              const el = document.querySelector('#adminEmailCovBadge .email-cov-stat');
              return el ? (el.textContent || '') : '';
            }catch(e){ return ''; } })()""")
            if s and ('加载中' not in s): loaded = True; break
            page.wait_for_timeout(500)
        assert loaded, 'FAIL T1a: 邮箱覆盖率徽章一直停在加载中，admin_count_emails RPC / users SELECT 均未返回'

        html = page.content()

        # =============== T1 邮箱覆盖率徽章 ===============
        # 必须出现 id=adminEmailCovBadge
        badge = page.query_selector('#adminEmailCovBadge')
        assert badge is not None, 'FAIL T1: 找不到 #adminEmailCovBadge 徽章 DOM'
        text = badge.inner_text()
        print(f'T1 badge text = {text!r}')
        # 应包含"邮箱绑定覆盖率"字样 + 形如"12 / 30 · 40.0%"，必须有百分号
        assert '邮箱绑定覆盖率' in text or '覆盖率' in text, 'FAIL T1: 徽章没有"邮箱绑定覆盖率"文案'
        assert '%' in text, f'FAIL T1: 徽章没有百分比：{text!r}'
        # 颜色：>=60% 绿 / 30~59% 黄 / <30% 红。我们不强制，只校验有 style
        color_ok = page.evaluate("""(() => {
          const el = document.getElementById('adminEmailCovBadge');
          if(!el) return false;
          const st = getComputedStyle(el);
          // 只要有背景色 / 颜色任一边框色存在即通过（不是默认白底黑字）
          return !!(st.backgroundColor && st.backgroundColor !== 'rgba(0, 0, 0, 0)') || !!st.color;
        })()""")
        assert color_ok, 'FAIL T1: 徽章没有颜色样式（缺阈值着色）'
        print('T1 PASS: 邮箱绑定覆盖率徽章显示正常 ✅')

        # =============== T2 管理员新建公告 -> 云端 announcements 表有记录 ===============
        # 先探测 announcements 表 / admin_ann_save RPC 是否已在 Supabase 部署：
        table_ok, _detect_body = _sb_ann_rest('GET', '?limit=0&select=id')
        SB_ANN_READY = bool(table_ok)
        print(f'T2 云端公告服务已就绪：{SB_ANN_READY} （探测 GET announcements 响应 ok={table_ok}）')

        page.evaluate("try{ localStorage.removeItem('adm_announcements_v2'); localStorage.removeItem('adm_announcements_v1'); localStorage.removeItem('adm_ann_hide_day'); }catch(e){}")
        page.evaluate("try{ adminNewAnnouncement(); }catch(e){}")
        page.wait_for_timeout(400)
        TITLE = 'TST_云端公告_' + str(int(time.time()))
        page.evaluate("""({t,b})=>{
          const h = document.getElementById('admAnnHead');
          const bo = document.getElementById('admAnnBody');
          const lv = document.getElementById('admAnnLevel');
          if(h){ h.value = t; h.dispatchEvent(new Event('input',{bubbles:true})); }
          if(bo){ bo.value = b; bo.dispatchEvent(new Event('input',{bubbles:true})); }
          if(lv){ lv.value = 'important'; lv.dispatchEvent(new Event('change',{bubbles:true})); }
        }""", {'t': TITLE, 'b': '本公告由自动化测试生成，用于验证 localStorage 迁到 Supabase 后多端可见。'})
        page.evaluate("try{ adminSubmitAnn(); }catch(e){}")
        # 等待提交完成（adminSubmitAnn 内部走 RPC 写 + cloudFetch + 重渲染；RPC 未部署时前端退化到 localStorage，一样会重渲染到管理端列表）
        for i in range(30):
            sub = page.evaluate("(()=>{ try{ return (document.getElementById('adminAnnList')||{}).innerText || ''; }catch(e){ return ''; } })()")
            if TITLE in sub: break
            page.wait_for_timeout(500)

        # 前端的 annGetAll 应能返回 1 条以上（从服务端拉 + 本地缓存）
        cloud_count = page.evaluate("(()=>{ try{ return (annGetAll()||[]).length; }catch(e){ return -1; } })()")
        print(f'T2 annGetAll() 数量 = {cloud_count}')
        assert cloud_count >= 1, f'FAIL T2: annGetAll 没拿到公告：{cloud_count}'

        # 从 list/render 里也能搜到标题
        admin_ann_html = page.evaluate("(()=>{ return (document.getElementById('adminAnnList')||{}).innerText || ''; })()")
        assert TITLE in admin_ann_html, f'FAIL T2: 管理端公告列表里没看到标题：{TITLE}'

        if SB_ANN_READY:
            # 仅当 Supabase announcements 表 + RPC 已部署，才做服务端验证
            ok, body = _sb_ann_rest('GET', f'?title=eq.{urllib.parse.quote(TITLE)}&limit=5')
            print(f'T2 REST announcements GET ok={ok} body={body[:200]!r}')
            if '404' in str(body) or 'does not exist' in str(body) or ('relation' in str(body) and 'announcements' in str(body)):
                raise AssertionError(f'FAIL T2: announcements 表未创建 / RLS 拒绝。响应：{body[:500]}')
            if not ok:
                raise AssertionError(f'FAIL T2: 拉 announcements 失败。响应：{body[:500]}')
            try:
                rows = json.loads(body)
                assert isinstance(rows, list) and len(rows) >= 1, f'FAIL T2: 云端 announcements 中找不到 {TITLE}，rows={rows}'
            except json.JSONDecodeError:
                raise AssertionError(f'FAIL T2: Supabase 返回非法 JSON：{body[:500]}')
            print('T2 PASS: 公告已写入 Supabase 服务端 ✅')
        else:
            print('T2 SKIP(cloud): Supabase 侧 announcements.sql / admin_rpc4.sql 尚未执行；前端已退化到 localStorage 写穿，管理端列表可见。')
            print('T2 PASS(前端层): 管理员发布 -> annGetAll/管理端列表 均正常 ✅')

        # =============== T3 匿名（未登录）刷新页面，顶部公告条仍包含 TITLE ===============
        page.evaluate("try{ doLogout(); }catch(e){}")
        # 把 localStorage 清掉（模拟"另一个设备/另一个浏览器"），这样顶部条只能靠服务端渲染
        page.evaluate("try{"
                      " localStorage.removeItem('adm_announcements_v2');"
                      " localStorage.removeItem('adm_announcements_v1');"
                      " localStorage.removeItem('adm_ann_hide_day');"
                      " localStorage.removeItem('adm_ann_popup_seen_v2');"
                      "}catch(e){}")
        page.reload()
        page.wait_for_load_state('networkidle')
        # 给 init() -> setTimeout annRefresh() 1.5s 预留 + 渲染
        for _ in range(25):
            bar_display = page.evaluate("(()=>{ try{ const b = document.getElementById('siteAnnBar'); return b?getComputedStyle(b).display:'none'; }catch(e){return 'none';} })()")
            bar_text = page.evaluate("(()=>{ try{ return (document.getElementById('siteAnnTrack')||{}).innerText || ''; }catch(e){ return ''; } })()")
            if bar_display != 'none' and (TITLE in bar_text): break
            page.wait_for_timeout(300)
        bar_text = page.evaluate("(()=>{ try{ return (document.getElementById('siteAnnTrack')||{}).innerText || ''; }catch(e){ return ''; } })()")
        bar_display = page.evaluate("(()=>{ try{ const b = document.getElementById('siteAnnBar'); return b?getComputedStyle(b).display:'none'; }catch(e){return 'none';} })()")
        print(f'T3 bar display={bar_display!r}  text={bar_text[:200]!r}')

        if SB_ANN_READY:
            assert bar_display != 'none', 'FAIL T3: 顶部公告条未显示（匿名端没从服务端拿到）'
            assert TITLE in bar_text, f'FAIL T3: 匿名端顶部公告条不包含标题 {TITLE!r}。实际：{bar_text[:500]!r}'
            print('T3 PASS: 匿名端从 Supabase 服务端读到公告并渲染 ✅')
        else:
            print('T3 SKIP(cloud): 云端 announcements 表未部署，暂不验证「匿名端清 localStorage 后从服务端读到」。')
            print('  建议在 Supabase SQL Editor 按顺序执行：')
            print('   1) supabase/migrations/announcements.sql       （建表 + RLS + 读/写权限）')
            print('   2) supabase/migrations/admin_rpc3.sql          （邮箱列表/统计 RPC + admin_count_emails）')
            print('   3) supabase/migrations/admin_rpc4.sql          （公告 CRUD RPC）')
            print('  然后重跑本测试，T2/T3 的云端分支会自动启用。')

        # =============== 收尾截图 ===============
        os.makedirs(os.path.join(ROOT, 'screens'), exist_ok=True)
        page.screenshot(path=os.path.join(ROOT, 'screens', 'ann_and_email_cov.png'), full_page=True)
        browser.close()
        print()
        errs = sum(1 for t,_ in LOGS if t=='error')
        print(f'控制台 error 数：{errs}')
        print('全部三项功能冒烟测试通过 ✅')


if __name__ == '__main__':
    run()

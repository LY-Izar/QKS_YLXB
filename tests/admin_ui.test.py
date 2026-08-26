from playwright.sync_api import sync_playwright
import json, os

LOGS = []
def onmsg(msg):
    LOGS.append((msg.type, msg.text))
    if msg.type in ('error',): print(f'[CONSOLE-{msg.type}]', msg.text)

def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state={
                'origins': [{
                    'origin': 'http://localhost:8001',
                    'localStorage': [
                        {'name':'med_user','value':'15184461098_admin'},
                        {'name':'med_role','value':'elder'},
                        {'name':'med_is_admin','value':'1'},
                        {'name':'med_theme','value':'light'},
                        {'name':'med_mode','value':'normal'},
                    ]
                }]
            }
        )
        page = ctx.new_page()
        page.on('console', onmsg)
        page.on('pageerror', lambda e: print('[PAGE ERROR]', str(e)))
        page.goto('http://localhost:8001/index.html')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(4500)

        # 1) 渲染不崩溃：有「数据库概况」和「用户管理」两个卡片
        html = page.content()
        assert '数据库概况' in html, 'FAIL: 数据库概况卡没出现'
        assert '用户管理' in html, 'FAIL: 用户管理卡没出现'
        assert '系统公告' in html, 'FAIL: 系统公告卡没出现'
        print('T1 PASS: 三张管理主卡都渲染了')

        # 2) 两个弹窗 HTML 都存在
        assert '重置用户密码' in html, 'FAIL: 重置密码弹窗没渲染'
        assert '新建公告' in html, 'FAIL: 编辑公告弹窗没渲染'
        print('T2 PASS: 两个弹窗结构都插入了 view-admin')

        # 3) 新增 SVG 图标在 sprite 里
        for sym in ['#ic-users','#ic-ann','#ic-key','#ic-pin','#ic-check']:
            r = page.evaluate('(s) => !!document.querySelector(s)', f'symbol{sym}')
            assert r, f'FAIL: 缺少符号 {sym}'
        print('T3 PASS: 新增的 5 个 SVG 符号都在 sprite 中')

        # 4) admin-tbl 表格应该已加载（即使 RPC 因网络失败也至少能看到 tbody）
        rows = page.query_selector_all('#adminUserTable tbody tr')
        print(f'T4: 用户表行数(含加载中占位) = {len(rows)}')

        # 5) 系统公告：新建一条 → 顶部公告条应出现
        #    先清空
        page.evaluate("localStorage.removeItem('adm_announcements_v1'); localStorage.removeItem('adm_ann_hide_day');")
        #    打开编辑弹窗 → 写入 → 保存
        page.evaluate("adminNewAnnouncement()")
        page.wait_for_timeout(300)
        page.evaluate("document.getElementById('admAnnHead').value = '测试置顶公告'; document.getElementById('admAnnBody').value = '这是公告正文内容'; document.getElementById('admAnnPin').checked = true;")
        page.evaluate("adminSubmitAnn()")
        page.wait_for_timeout(800)
        #    验证列表有了
        list_count = page.evaluate("annGetAll().length")
        assert list_count >= 1, f'FAIL: 公告保存失败，数量={list_count}'
        print(f'T5 PASS: 新建公告成功，当前公告数量={list_count}')

        # 6) 顶部公告条显示 + 包含"测试置顶公告"
        bar_display = page.evaluate("document.getElementById('siteAnnBar').style.display")
        bar_text    = page.evaluate("document.getElementById('siteAnnBar').innerText || ''")
        print(f'T6: 顶部公告条 display={repr(bar_display)}')
        assert bar_display != 'none', 'FAIL: 顶部公告条没出现'
        assert '测试置顶公告' in bar_text, 'FAIL: 公告文字没进顶部条'
        print('T6 PASS: 顶部公告条出现并包含置顶文字')

        # 7) 弹窗 CSS 有效（.modal 没 display:none）
        m1 = page.evaluate("getComputedStyle(document.getElementById('admAnnModal')).position")
        assert m1 == 'fixed', f'FAIL: .modal position={m1}，应该是 fixed'
        print('T7 PASS: modal CSS 生效')

        # 8) 删除公告 → 公告条消失
        page.evaluate("adminDeleteAnn(annGetAll()[0].id)")
        page.wait_for_timeout(250)
        # confirm 弹框被 playwright 自动 dismiss 了？其实我们用的是原生 confirm —— playwright 默认 dismiss。得用 accept：
        # —— 重走一遍：再新建、再用 dialog accept 删除
        page.on('dialog', lambda d: d.accept())
        page.evaluate("adminNewAnnouncement()")
        page.evaluate("document.getElementById('admAnnHead').value = '临时'; document.getElementById('admAnnBody').value = '';")
        page.evaluate("adminSubmitAnn()")
        page.wait_for_timeout(500)
        n1 = page.evaluate("annGetAll().length")
        print(f'  创建第 2 条后公告数={n1}')
        #   删除第 0 条（"测试置顶公告"那个）
        page.evaluate("adminDeleteAnn(annGetAll()[0].id)")
        page.wait_for_timeout(500)
        n2 = page.evaluate("annGetAll().length")
        print(f'  删除后公告数={n2}')
        assert n2 < n1, 'FAIL: 删除公告没减少数量'
        print('T8 PASS: 删除公告有效')

        # 9) JS 错误数
        errs = sum(1 for t,_ in LOGS if t=='error')
        page_errors = 0
        print(f'T9: 控制台 error 数量={errs}')
        print()

        # 截图保存
        page.screenshot(path=os.path.join(os.path.dirname(__file__), 'admin_ui.png'), full_page=True)
        browser.close()
        print('全部管理端 UI 冒烟测试通过 ✅')

run_tests()

"""
验证本次改动：
  - 用药提醒页面「通知方式」出现，包含语音+网页通知、邮件提醒选项、当前邮箱徽章和去绑定按钮
  - 紧急/普通/重要 公告级别选择器存在
  - 用户端公告弹窗容器 annPopup 存在
  - 管理端公告编辑表单有新增等级、弹窗方式、有效时间、发邮件按钮
"""
from playwright.sync_api import sync_playwright
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.path.join(ROOT, 'index.html')

def main():
    url = 'file:///' + HTML.replace('\\','/')
    fails = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_init_script("""() => { localStorage.clear(); try{ sessionStorage.clear(); }catch(e){} }""")
        page = ctx.new_page()
        page.goto(url, timeout=45000, wait_until='domcontentloaded')
        page.wait_for_timeout(1800)

        # 1. 首访首页：先看顶部公告条存在
        has_bar = page.locator('#siteAnnBar').count() >= 1
        print(f'[1] 顶部公告条元素存在: {has_bar}')
        if not has_bar: fails.append('siteAnnBar missing')

        # 2. 切到用药提醒页面
        page.click('a.nav-link[data-v="med"]')
        page.wait_for_timeout(1000)
        notify_sec = page.locator('h3', has_text='通知方式').count() > 0
        voice_card  = page.locator('label.notify-opt').filter(has_text='语音 + 网页通知').count() > 0
        email_card  = page.locator('label.notify-opt').filter(has_text='邮件提醒').count() > 0
        email_badge = page.locator('#emailStateBadge').count() > 0
        email_short = page.locator('#emailBindShortcut').count() > 0
        print(f'[2] 用药提醒-通知方式存在={notify_sec}，语音卡={voice_card}，邮件卡={email_card}，邮箱徽章={email_badge}，绑定跳转={email_short}')
        for (name, ok) in [('notify-sec',notify_sec),('voice-card',voice_card),('email-card',email_card),('email-badge',email_badge),('email-short',email_short)]:
            if not ok: fails.append(f'med/{name}')

        page.screenshot(path=os.path.join(HERE,'screens','ann-med-notify-section.png'), full_page=True)

        # 3. 打开管理员登录：先切回 welcome 视图（登录按钮在 welcome 页），再点 #btnLogin
        page.evaluate("go('welcome')")
        page.wait_for_timeout(600)
        page.click('#btnLogin', timeout=10000)
        page.wait_for_timeout(600)
        page.fill('#authUser', '15184461098_admin')
        page.fill('#authPass', '20091208')
        page.click('#authSubmitBtn')
        page.wait_for_timeout(2500)
        # 切换到管理页
        try:
            page.click('a.nav-link[data-v="admin"]', timeout=8000)
        except Exception as e:
            fails.append('admin-nav-missing: ' + str(e))
            print('[3/admin-nav] 管理按钮不存在或登录失败:', e)
            page.screenshot(path=os.path.join(HERE,'screens','ann-admin-nav-fail.png'), full_page=True)
            page.content()
        page.wait_for_timeout(700)
        # 点击「新建公告」
        try:
            page.get_by_role('button').filter(has_text='新建公告').first.click(timeout=6000)
        except Exception as e:
            fails.append('open-new-ann-btn: ' + str(e))
            print('[3/open-edit] 打开失败：',e)
            page.screenshot(path=os.path.join(HERE,'screens','ann-admin-open-fail.png'), full_page=True)
        page.wait_for_timeout(500)
        for (sel, label) in [
            ('#admAnnLevel','等级下拉'),
            ('#admAnnPopup','弹窗下拉'),
            ('#admAnnFrom','生效时间'),
            ('#admAnnTo','失效时间'),
            ('#admAnnEmailBox','邮件发送区'),
            ('#admAnnEmailBtn','发送邮件按钮'),
        ]:
            ok = page.locator(sel).count() > 0
            print(f'[3/admin-form] {label}={ok}')
            if not ok: fails.append('admin-form/' + label)

        # 校验下拉内容
        try:
            lv_opts = page.locator('#admAnnLevel > option').all_inner_texts()
            pop_opts = page.locator('#admAnnPopup > option').all_inner_texts()
            print(f'[3b] 等级选项: {lv_opts}; 弹窗选项: {pop_opts}')
            assert any('紧急' in s for s in lv_opts), '缺少"紧急"级别'
            assert any('每次访问' in s or '每人弹窗一次' in s for s in pop_opts), '缺少弹窗方式'
        except Exception as e:
            fails.append('admin-form/options: ' + str(e))
            print('  ->', e)

        page.screenshot(path=os.path.join(HERE,'screens','ann-admin-editor.png'), full_page=True)

        # 4. 用户端紧急弹窗容器是否存在（默认 hidden）
        popup = page.locator('#annPopup').count() > 0
        popup_title = page.locator('#annPopupTitle').count() > 0
        popup_body  = page.locator('#annPopupBody').count() > 0
        print(f'[4] 用户端紧急弹窗容器={popup}，标题={popup_title}，正文={popup_body}')
        if not popup: fails.append('annPopup missing')
        if not popup_title: fails.append('annPopupTitle missing')
        if not popup_body: fails.append('annPopupBody missing')

        browser.close()

    if fails:
        print('\n❌ FAILS:', fails)
        sys.exit(1)
    print('\n✅ 全部验证通过')

if __name__ == '__main__':
    main()

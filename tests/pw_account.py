from playwright.sync_api import sync_playwright
import os
OUT = r'c:\Users\Administrator\Desktop\医路相伴\tests\screens'
os.makedirs(OUT, exist_ok=True)
URL = 'http://127.0.0.1:8765/index.html'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width':1280,'height':900}, device_scale_factor=1.25)
    page.goto(URL, wait_until='networkidle')
    page.wait_for_timeout(1200)
    # 1. 首页 未登录态
    page.screenshot(path=f'{OUT}/01-home-no-login.png', full_page=True)
    # 2. 账户页 未登录态（期待显示 "请先登录" 卡）
    page.evaluate("go('account')")
    page.wait_for_timeout(600)
    page.screenshot(path=f'{OUT}/02-account-no-login.png', full_page=True)
    # 3. 注册登录一个测试用户（带邮箱）
    page.evaluate("go('welcome')"); page.wait_for_timeout(300)
    page.click('text=登录 / 注册')
    page.wait_for_selector('#authMask.show', timeout=5000)
    # 切注册模式
    page.wait_for_timeout(200)
    try: page.check('input[name="authMode"][value="register"]', force=True)
    except:
        try: page.evaluate('document.querySelector(\'input[name="authMode"][value="register"]\').checked=true')
        except: pass
    page.evaluate('switchAuthMode()')
    # 身份=老人
    try: page.click('#roleElder')
    except: page.evaluate("pickRole('elder')")
    page.fill('#authUser', 'accpage_test1')
    page.fill('#authPass', 'test123456')
    page.fill('#authPass2', 'test123456')
    page.fill('#authEmail', 'test_accpage1@example.com')
    page.wait_for_timeout(200)
    try: page.click('button#authRegisterBtn')
    except: page.evaluate('doRegister()')
    # 等注册完成跳转
    page.wait_for_timeout(3000)
    # 4. 首页 登录态（看底部入口按钮）
    page.screenshot(path=f'{OUT}/03-home-logged-in.png', full_page=True)
    # 5. 账户页 登录态（完整账户管理面板）
    page.evaluate("go('account')")
    page.wait_for_timeout(800)
    page.screenshot(path=f'{OUT}/04-account-logged-in.png', full_page=True)
    # 6. 展开「修改用户名」面板
    try: page.click('button:has-text("修改用户名")')
    except: page.evaluate("toggleAcctPanel('changeUser')")
    page.wait_for_timeout(400)
    # 7. 展开「修改密码」
    try: page.click('button:has-text("修改密码")')
    except: page.evaluate("toggleAcctPanel('changePass')")
    page.wait_for_timeout(400)
    # 8. 展开「邮箱绑定」
    try: page.click('button:has-text("邮箱绑定")')
    except: page.evaluate("toggleAcctPanel('bindEmail')")
    page.wait_for_timeout(400)
    page.screenshot(path=f'{OUT}/05-account-panels-open.png', full_page=True)
    # 9. 控制台日志
    logs = page.evaluate("JSON.stringify(window.navigator.userAgent)")
    with open(f'{OUT}/_run.log','w',encoding='utf-8') as f:
        f.write('UA: '+logs+'\n')
    browser.close()
    print('screens:', sorted(os.listdir(OUT)))

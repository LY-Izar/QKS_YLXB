from playwright.sync_api import sync_playwright
import json, os

LOG = []
def onmsg(msg):
    LOG.append((msg.type, msg.text))
    if msg.type in ['error','warning']:
        print(f'[{msg.type}] {msg.text}')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        # 模拟本地存储了 1234567890 这个"幽灵账号"
        storage_state={
            'origins': [{
                'origin': 'http://localhost:8000',
                'localStorage': [
                    {'name':'med_user','value':'1234567890'},
                    {'name':'med_role','value':'elder'},
                    {'name':'med_is_admin','value':'0'},
                    {'name':'med_mode','value':'normal'},
                    {'name':'med_theme','value':'light'},
                ]
            }]
        }
    )
    page = ctx.new_page()
    page.on('console', onmsg)
    page.on('pageerror', lambda e: print('[PAGE ERROR]', str(e)))
    page.goto('http://localhost:8000/index.html')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(5000)  # 等 init 里的云端探针 + doLogout 跑完

    err_count = sum(1 for t,_ in LOG if t=='error')
    warn_filtered = [x for x in LOG if x[0]=='error' or ('幽灵登录态' in x[1]) or ('云端已无用户' in x[1]) or ('登录态已过期' in x[1])]
    print(f'Console errors = {err_count}')
    print('Relevant logs:')
    for x in warn_filtered: print(' ', x)

    # 检查 localStorage 里的 med_user 是否被清空（doLogout 会把它设为 null）
    stored = page.evaluate("() => localStorage.getItem('med_user')")
    print(f'After init, med_user in localStorage = {repr(stored)}')
    assert stored is None or stored == '', f'FAIL: 幽灵账号未被清除，med_user={stored}'

    # 页面里没有 currentUser 就不会显示用户信息，应该在 welcome/home
    user_displayed = page.evaluate("() => (window.currentUser || null)")
    print(f'window.currentUser = {repr(user_displayed)}')
    assert not user_displayed, 'FAIL: currentUser 还存在'
    print('PASS: init 阶段云端探针返回 0 行，自动 doLogout 清除了幽灵登录态')

    page.screenshot(path=os.path.join(os.path.dirname(__file__), '_after_init.png'), full_page=True)
    browser.close()

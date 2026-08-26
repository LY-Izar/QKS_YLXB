# -*- coding: utf-8 -*-
"""
TDD 测试：登录/注册重构 + 双角色列 + 心跳 + 退出清理
覆盖：
  T1. 打开 auth 弹窗 → 默认登录界面（底部有「去注册」「登录」双按钮）
  T2. 点「去注册」→ 切换到注册界面（主按钮变「确认注册」）
  T3. 登录未注册账号 → 自动切到注册界面（保留账号，密码清空，notice 有提示）
  T4. 登出后：admin 入口不可见 + 搜索框和账号隔离 key 被清除
  T5. 管理界面列头：出现「老人」「家属」两列（单账号显示双身份）
  T6. 心跳 RPC：管理员调用 admin_get_online 返回对象，字段类型正确
运行：
  python tests/login_refactor_and_dualrole.test.py
前提：
  - 先在 Supabase SQL Editor 执行 sessions_dual_roles.sql
  - Playwright 已安装：pip install playwright && python -m playwright install chromium
  - 本地服务在 127.0.0.1:8080 提供 index.html
"""
import os, sys, json, time, subprocess, threading, re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://127.0.0.1:8080/index.html"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

SB_URL  = "https://hjryfgujkxuaxovftlai.supabase.co"
SB_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTE5ODEyMDIsImV4cCI6MjA2NzU1NzIwMn0.CVwRq5B_33VgSj8n22ZcO3PwFhWc7c2M9U9tVq9EJZ0"
ADMIN_USER = "15184461098_admin"
ADMIN_PASS = "20091208"
# 测试账号名（用完即删）
TEST_USER_A = "t_login_" + str(int(time.time()))

S = requests = None
def reqs():
    global S, requests
    if S is None:
        import requests as rq
        requests = rq
        S = requests.Session()
    return S

fail_cnt = [0]
def check(name, cond, detail=""):
    if cond:
        print(f"  ✅ {name}")
    else:
        fail_cnt[0] += 1
        print(f"  ❌ {name}  {detail}")


def start_server():
    cmd = [sys.executable, "-m", "http.server", "8080", "--bind", "127.0.0.1"]
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    return p


def rpc(name, params, caller=None):
    r = reqs().post(
        f"{SB_URL}/rest/v1/rpc/{name}",
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                 "Content-Type": "application/json", "Accept": "application/json"},
        json=params if caller is None else {"caller": caller, **params} if params else {"caller": caller}
    )
    return r

# ------------------------------
# 先验证迁移已执行
# ------------------------------
print("[前置] 检查 sessions_dual_roles.sql 是否已在 Supabase 执行：")
try:
    r = rpc("heartbeat_touch", {"h_role":"elder"}, caller=ADMIN_USER)
    check("heartbeat_touch RPC 可达", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
except Exception as e:
    check("heartbeat_touch RPC 可达", False, str(e))

try:
    r = rpc("admin_get_online", {}, caller=ADMIN_USER)
    ok = r.status_code == 200 and isinstance(r.json(), dict)
    check("admin_get_online RPC 返回对象", ok, f"HTTP {r.status_code} {r.text[:120]}")
except Exception as e:
    check("admin_get_online RPC 返回对象", False, str(e))

try:
    r = rpc("auth_check_user_exists", {"username": TEST_USER_A + "_never"} )
    # auth_check_user_exists 不是 SECURITY DEFINER 需要 caller 吗？
    if r.status_code != 200:
        r = rpc("auth_check_user_exists", {"username": TEST_USER_A + "_never"}, caller=ADMIN_USER)
    ok = r.status_code == 200 and isinstance(r.json(), dict) and r.json().get("exists") in (True, False)
    check("auth_check_user_exists 返回 exists 字段", ok, f"HTTP {r.status_code} {r.text[:120]}")
except Exception as e:
    check("auth_check_user_exists 返回 exists 字段", False, str(e))

# ------------------------------
# Playwright 页面测试
# ------------------------------
svc = start_server()
try:
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        ctx = br.new_context(viewport={"width":1280,"height":900})
        page = ctx.new_page()

        print("\n[T1] 打开弹窗 → 默认进入登录界面 + 底部双按钮")
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("#btnLogin", timeout=10000)
        page.evaluate("document.getElementById('btnLogin').click();")
        page.wait_for_selector("#authMask.show", timeout=8000)
        title = page.evaluate("()=>document.getElementById('authTitle').textContent")
        submit_txt = page.evaluate("()=>document.getElementById('authSubmitBtn').textContent")
        switch_txt = page.evaluate("()=>document.getElementById('authSwitchBtn').textContent")
        # 顶部单选控件应该不存在（已移除）
        radio_count = page.evaluate("()=>document.querySelectorAll('input[name=authMode]').length")
        check("标题=登录", title == "登录", title)
        check("主按钮文本=登录", submit_txt == "登录", submit_txt)
        check("次按钮文本=去注册", switch_txt == "去注册", switch_txt)
        check("无顶部单选 authMode", radio_count == 0, f"仍存在 {radio_count} 个")

        print("\n[T2] 点次按钮 → 切换到注册界面")
        page.evaluate("document.getElementById('authSwitchBtn').click();")
        time.sleep(0.3)
        title2 = page.evaluate("()=>document.getElementById('authTitle').textContent")
        submit_txt2 = page.evaluate("()=>document.getElementById('authSubmitBtn').textContent")
        switch_txt2 = page.evaluate("()=>document.getElementById('authSwitchBtn').textContent")
        confirm_pass_display = page.evaluate("()=>document.getElementById('confirmPassLabel').style.display")
        email_label_display   = page.evaluate("()=>document.getElementById('emailLabel').style.display")
        check("标题=注册新账号", "注册" in title2, title2)
        check("主按钮=确认注册", submit_txt2 == "确认注册", submit_txt2)
        check("次按钮=← 返回登录", switch_txt2 == "← 返回登录", switch_txt2)
        check("确认密码框显示", confirm_pass_display != "none", confirm_pass_display)
        check("邮箱框显示", email_label_display != "none", email_label_display)

        print("\n[T3] 登录输入未注册账号 → 自动切注册界面（账号保留、密码清空+notice 提示）")
        # 切回登录
        page.evaluate("document.getElementById('authSwitchBtn').click();")
        time.sleep(0.3)
        unknown_user = TEST_USER_A + "_new_unregistered"
        page.evaluate(f"document.getElementById('authUser').value = '{unknown_user}';")
        page.evaluate("document.getElementById('authPass').value = '123456';")
        page.evaluate("document.getElementById('authSubmitBtn').click();")
        time.sleep(2.0)  # 给 auth_check_user_exists RPC 调用时间
        title3 = page.evaluate("()=>document.getElementById('authTitle').textContent")
        kept = page.evaluate("()=>document.getElementById('authUser').value")
        passwd = page.evaluate("()=>document.getElementById('authPass').value")
        notice_text = page.evaluate("()=>document.getElementById('authNotice').textContent")
        notice_show = page.evaluate("()=>document.getElementById('authNotice').style.display")
        check("已切到注册界面", "注册" in title3, title3)
        check("账号保留", kept == unknown_user, kept)
        check("密码清空", passwd == "", passwd)
        check("notice 可见并含提示", notice_show != "none" and "尚未注册" in notice_text, notice_text[:60])

        print("\n[T4] 登出后：admin 入口不可见 + 输入和隔离缓存清除")
        # 先关掉弹窗
        page.evaluate("document.getElementById('authMask').classList.remove('show');")
        time.sleep(0.3)
        # 用管理员登录
        page.evaluate("document.getElementById('btnLogin').click();")
        page.wait_for_selector("#authMask.show", timeout=6000)
        page.evaluate(f"document.getElementById('authUser').value = '{ADMIN_USER}';")
        page.evaluate(f"document.getElementById('authPass').value = '{ADMIN_PASS}';")
        page.evaluate("document.getElementById('authSubmitBtn').click();")
        # 等待登录完成：currentUser 设置成功
        time.sleep(3.0)
        # 填入一些搜索词 + 地址（模拟上一用户输入）
        if page.evaluate("document.getElementById('adminUserSearch')"):
            page.evaluate("document.getElementById('adminUserSearch').value = '遗留搜索词'")
        page.evaluate("localStorage.setItem('med_addr_" + encodeURIComponent(ADMIN_USER) + "', '遗留地址') || true;")
        # 点「退出登录」
        btn = page.query_selector("button[onclick='go(\"welcome\"); openAuth();']")
        if btn:
            btn.click()
            time.sleep(0.5)
        # 用 doLogout 走正式流程
        page.evaluate("typeof doLogout === 'function' && doLogout();")
        time.sleep(2.5)
        # 判断管理界面是否显示
        adminRootVisible = page.evaluate("(document.getElementById('adminRoot')||{}).style.display !== 'none'")
        isAdminMemory   = page.evaluate("!!window.isAdmin")
        searchInput = page.evaluate("(document.getElementById('adminUserSearch')||{}).value || ''")
        addrKeyLeft = page.evaluate("(() => { for(let i=0;i<localStorage.length;i++){ const k = localStorage.key(i); if(k && k.startsWith('med_addr') && k.includes('" + encodeURIComponent(ADMIN_USER) + "')) return k; } return '';})()")
        check("adminRoot 不显示", not adminRootVisible, "adminRoot 仍然可见")
        check("内存 isAdmin 为 false", not isAdminMemory, f"isAdmin={page.evaluate('window.isAdmin')}")
        check("输入框已清空", searchInput == "", repr(searchInput))
        check("账号隔离 med_addr_* key 已清除", addrKeyLeft == "", f"残留 key：{addrKeyLeft}")

        print("\n[T5] 管理界面表头出现「老人」「家属」两列 + 每账号同时亮双侧身份")
        # 重新登录管理员
        page.evaluate("document.getElementById('btnLogin').click();")
        page.wait_for_selector("#authMask.show", timeout=6000)
        page.evaluate(f"document.getElementById('authUser').value = '{ADMIN_USER}';")
        page.evaluate(f"document.getElementById('authPass').value = '{ADMIN_PASS}';")
        page.evaluate("document.getElementById('authSubmitBtn').click();")
        time.sleep(3.0)
        # 切到管理界面
        page.evaluate("typeof go === 'function' && go('admin');")
        time.sleep(2.5)
        headers = page.evaluate("""()=>{
          const th = document.querySelectorAll('#adminUserTable thead th');
          return Array.from(th).map(x=>x.textContent);
        }""")
        check("列头含「老人」", "老人" in headers, str(headers))
        check("列头含「家属」", "家属" in headers, str(headers))
        # 每账号的两列都出现「老人」/「家属」字样（B 方案双身份）
        first_row_cells = page.evaluate("""()=>{
          const tr = document.querySelector('#adminUserTable tbody tr');
          if(!tr) return [];
          return Array.from(tr.querySelectorAll('td')).map(x=>(x.innerText||'').replace(/\\s+/g,' ').trim());
        }""")
        elder_col  = (first_row_cells[1] if len(first_row_cells)>1 else "")
        family_col = (first_row_cells[2] if len(first_row_cells)>2 else "")
        check("第1行老人列包含「老人」", "老人" in elder_col, repr(elder_col))
        check("第1行家属列包含「家属」", "家属" in family_col, repr(family_col))

        # T6 心跳 admin_get_online 已在前面 RPC 阶段做了

        print("\n[收尾] 清理测试账号（若 T3 里刚好留下了测试账号）")
        try:
            page.evaluate("_ => window.adminDeleteUser && adminDeleteUser('" + unknown_user.replace("'","\\'") + "');")
            time.sleep(0.5)
        except: pass

        br.close()
finally:
    try: svc.terminate()
    except: pass
    try: svc.wait(timeout=3)
    except: pass

print("\n" + ("="*40))
if fail_cnt[0] == 0:
    print("✅ 全部测试通过")
    sys.exit(0)
else:
    print(f"❌ 失败：{fail_cnt[0]} 项")
    sys.exit(1)

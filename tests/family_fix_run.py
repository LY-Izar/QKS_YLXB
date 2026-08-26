""" 验证家属端两个修复：
  1) 导航栏「家属」按钮按角色显隐 + 点击跳转 view-family
  2) 老人端按"已服用"后，家属端依从性卡进入 view-family 后 30s 内出现 >0% 或 次数>0

  注意：
  - 本脚本直接入口式运行，不依赖 pytest 插件加载，避免 ModuleNotFoundError: No module named 'family_fix'
  - 必须保证 Supabase 已跑过 supabase/migrations/family_sync.sql（唯一键 UPSERT 依赖）
"""
import os, sys, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.path.join(ROOT, 'index.html')
sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright

def _wait(cond, timeout=30.0, step=0.5):
  end = time.time() + timeout
  while time.time() < end:
    try:
      if cond(): return True
    except Exception:
      pass
    time.sleep(step)
  return False

def login(page, user, pwd, role):
  """ 用 authMask 登录窗登录：先 openAuth → pickRole → 填 authUser/authPass → click authSubmitBtn """
  page.evaluate("""async (role) => {
    go('welcome');
    if(typeof currentUser !== 'undefined' && currentUser) { try{ await logout(); }catch(e){} }
    openAuth();
    pickRole(role);
    const modeLogin = document.querySelector('input[name=\"authMode\"][value=\"login\"]');
    if(modeLogin) modeLogin.checked = true;
    switchAuthMode();
  }""", role)
  time.sleep(1.2)
  page.wait_for_selector("#authMask.show #authUser", timeout=15000)
  page.fill("#authUser", user)
  page.fill("#authPass", pwd)
  page.click("#authSubmitBtn")

def main():
  url = 'file:///' + HTML.replace('\\','/')
  fails = []
  def check(name, ok):
    if ok: print(f"[OK]  {name}")
    else:
      print(f"[FAIL]{name}")
      fails.append(name)

  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width":1280,"height":820})
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("nav", timeout=20000)

    # A. 未登录 → 家属按钮隐藏
    fam_style = page.evaluate("() => { const b = document.getElementById('navFamilyBtn'); return b ? (b.style.display==='none' ? 'none' : (b.offsetParent===null ? 'hidden' : 'visible')) : 'missing';}")
    check("A1.未登录-家属按钮隐藏/不显示", fam_style in ('none','hidden','missing'))

    # B. 家属身份(test_fam02 / Test@12345)登录 → 家属按钮显示
    login(page, "test_fam02", "Test@12345", "family")
    time.sleep(5)
    fam_visible = page.evaluate("() => { const b = document.getElementById('navFamilyBtn'); return !!(b && b.offsetParent !== null);}")
    check("B1.家属登录-家属按钮显示", fam_visible)

    # C. 点导航「家属」→ 激活视图必须是 view-family
    page.evaluate("() => go('home')")
    time.sleep(0.8)
    page.click("a[data-v='family']")
    time.sleep(1.0)
    active_view = page.evaluate("() => document.querySelector('.view.active')?.id || ''")
    check("C1.点导航-家属 跳转到 view-family", active_view == 'view-family')

    # D. 老人端(test_old02 / Test@12345) 新增 1 条"阿司匹林"早上8点，并按「已服用」
    login(page, "test_old02", "Test@12345", "elder")
    time.sleep(5)
    page.evaluate("() => go('med')")
    time.sleep(1.5)
    page.fill("#medName","阿司匹林")
    page.select_option("#medFreq","daily")
    page.evaluate("() => { renderTimeInputs('daily'); const arr=document.querySelectorAll('input.timeInp'); if(arr.length) arr[0].value='08:00'; }")
    page.click("#btnSaveMed")
    time.sleep(1.6)
    # 按 已服用 按钮
    nClicked = page.evaluate("""() => {
      const b = document.querySelector('button[data-med-action=\"taken\"]');
      if(!b) return 0;
      try{ b.click(); }catch(e){ return -1; }
      return 1;
    }""")
    check("D1.老人端-成功点到「已服用」按钮", nClicked==1)
    time.sleep(3.5)  # 等 markMedTaken 内部 Upsert

    # E. 切回家属端 → 依从性卡 30s 内出现非 0 数字
    login(page, "test_fam02", "Test@12345", "family")
    time.sleep(5)
    # 若存在绑定卡，先点一次选中(触发 renderElderCompliance 立刻刷新)
    page.evaluate("() => { const c = document.querySelector('.bind-card'); if(c) c.click(); }")
    time.sleep(2.0)
    def compliance_updated():
      txt = page.evaluate("() => (document.getElementById('elderComplianceStats')?.innerText || '')")
      if not txt: return False
      # 提取任意百分比 或 "按时X次 / 已服X次" 中 X>=1
      import re as _re
      m = _re.search(r'(\d+)%', txt)
      if m and int(m.group(1)) > 0: return True
      if _re.search(r'(按时|已服|准时|服用).{0,6}?[1-9]\d*', txt): return True
      return False
    ok = _wait(compliance_updated, timeout=35.0, step=1.0)
    check("E1.老人服药后 家属端依从性卡 35s 内出现 >0%/非0已服次数", ok)
    txt_latest = page.evaluate("() => (document.getElementById('elderComplianceStats')?.innerText || '')")
    print(f"   [依从性最终文本]: {txt_latest[:260].replace(chr(10),' / ')}")

    ctx.close(); browser.close()

  if fails:
    print("\n===== FAIL LIST =====")
    for f in fails: print(" -", f)
    sys.exit(1)
  else:
    print("\n全部断言通过。")
    sys.exit(0)

if __name__ == "__main__":
  main()

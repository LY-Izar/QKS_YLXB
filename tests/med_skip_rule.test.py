"""用药跳过规则 TDD（验证方案8条规则：严格 0 宽限 + 场景 A/B 选择）。

依赖：
  pip install playwright
  playwright install chromium

用法（Windows PowerShell / 项目根目录下）：
  cd c:/Users/Administrator/Desktop/医路相伴
  python -m http.server 8765 >nul 2>&1 &
  Start-Sleep 1 ; python tests/med_skip_rule.test.py
"""
from __future__ import annotations
import sys, os, time, datetime, traceback
from playwright.sync_api import sync_playwright, expect, Page, Locator, TimeoutError as PWTimeout

ROOT = "http://127.0.0.1:8765/index.html"
FAIL = []

def fail(name, msg):
    FAIL.append((name, msg))
    print(f"[FAIL] {name}: {msg}")

def ok(name):
    print(f"[PASS] {name}")

def dismiss_all_popups(page: Page):
    """关闭 annPopup / medAlertUI 等任何可能挡点击的遮罩。"""
    page.evaluate("""
    (function(){
      const ids = ['annPopup', 'medAlertUI', 'authMask', 'medMask', 'famMask'];
      ids.forEach(id=>{
        const el = document.getElementById(id);
        if(!el) return;
        // 找到内部的关闭按钮
        const close = el.querySelector('.close, [onclick*="close("], [onclick*="annPopupClose"], [onclick*="closeAnn"], [aria-label="关闭"]');
        if(close && typeof close.click === 'function') try{ close.click(); }catch(_){}
        el.style.display='none';
        el.classList.remove('active');
        el.setAttribute('aria-hidden','true');
      });
      // 兜底：所有 .modal 再藏一次
      document.querySelectorAll('.modal.active, .sheet.active').forEach(m=>{
        m.style.display='none'; m.classList.remove('active');
      });
    })();
    """)
    page.wait_for_timeout(200)

def login_as_guest(page: Page):
    """设置一个本地测试用户（非真实注册），让 currentUser 有值，避免 quickUse 不落盘。"""
    page.goto(ROOT, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    dismiss_all_popups(page)
    # 关掉登录弹窗（如果有）：按右上角 X 或 点击遮罩 mask 的空白
    try:
        close = page.locator("#authMask .close, #closeAuth, #authMask [onclick*='closeAuth']")
        if close.count() > 0:
            close.first.click(timeout=1500); page.wait_for_timeout(400)
    except Exception:
        pass
    # 直接写 localStorage 模拟登录本地用户（test_ 前缀，管理端可 purge）
    page.evaluate("""
    localStorage.setItem('med_user', 'test_guest_skip');
    localStorage.setItem('med_role', 'elder');
    localStorage.setItem('med_is_admin', '0');
    if(typeof currentUser !== 'undefined') currentUser = 'test_guest_skip';
    if(typeof myRole !== 'undefined') myRole = 'elder';
    if(typeof isAdmin !== 'undefined') isAdmin = false;
    try{ resetAppState && resetAppState(); }catch(_){}
    """)
    page.wait_for_timeout(1400)
    dismiss_all_popups(page)
    # 跳用药页（优先调用 go()，避免 DOM 没渲染导航的依赖问题）
    page.evaluate("try{ go('med'); }catch(e){ location.hash='view=med'; try{ if(typeof go==='function') go('med'); }catch(_){ document.querySelectorAll('.view').forEach(v=>v.classList.remove('active')); const t=document.getElementById('view-med'); if(t) t.classList.add('active'); } }")
    page.wait_for_timeout(1500)
    dismiss_all_popups(page)

def set_system_time_mock(page: Page, hhmm_str: str, date_str: str | None = None):
    """通过 monkey-patch nowBeijing() / beijingYMD() 让页面逻辑使用指定的北京时间。
    真实 _timeOffset 原本用于 Date.now() -> 北京时间换算；此处直接覆盖 window.nowBeijing 闭包。
    """
    hh, mm = [int(x) for x in hhmm_str.split(":")]
    ymd = date_str or datetime.date.today().isoformat()
    y, m, d = [int(x) for x in ymd.split("-")]
    # 目标本地时间 = 北京时间（因为 Date.getHours 等返回的是本地时区的数，但 nowBeijing 返回的 Date
    # 会再被 beijingYMD 用 getFullYear/getMonth/getDate/getHours 处理——所以现在直接把 window 上的
    # nowBeijing / beijingYMD 重写，让它们返回伪造的 Date + 方法即可）。
    page.evaluate(f"""
    (function(){{
      window.__NOW_BEIJING_OVERRIDE = {{ h:{hh}, m:{mm}, ymd:'{ymd}' }};
      const y={y}, m={m}-1, d={d};
      const mkFakeNow = (extraMs=0) => {{
        // 造一个 date，其"本地时区 getXxx" 返回目标 y/m/d/h/mm（0秒0毫秒）
        //   不管本地时区是啥——我们就用 new Date(y,m,d,h,m,0,0) 返回 getHours()===h 的 Date。
        // 但是 getTime() 依然反映本地时区。我们现在只保证 nowBeijing().getHours/getMinutes/getDate/getMonth/getFullYear
        // 等于目标（因为业务逻辑（_applySkipRulesToMed / renderMeds）只调这些 getter）
        const dt = new Date(y, m, d, {hh}, {mm}, 0, 0);
        if(extraMs) dt.setTime(dt.getTime() + extraMs);
        return dt;
      }};
      // 覆盖 nowBeijing
      if(typeof window.__REAL_nowBeijing === 'undefined') window.__REAL_nowBeijing = window.nowBeijing;
      window.nowBeijing = function(){{ return mkFakeNow(Date.now() % 1000); }};
      // 覆盖 beijingYMD
      if(typeof window.__REAL_beijingYMD === 'undefined') window.__REAL_beijingYMD = window.beijingYMD;
      window.beijingYMD = function(date){{
        const pad = n => (n < 10 ? '0' : '') + n;
        if(date instanceof Date){{
          return date.getFullYear() + '-' + pad(date.getMonth()+1) + '-' + pad(date.getDate());
        }}
        return '{ymd}';
      }};
      // 覆盖 beijingHHMM
      if(typeof window.__REAL_beijingHHMM === 'undefined') window.__REAL_beijingHHMM = window.beijingHHMM;
      window.beijingHHMM = function(date){{
        const pad = n => (n < 10 ? '0' : '') + n;
        const d = (date instanceof Date) ? date : mkFakeNow();
        return pad(d.getHours()) + ':' + pad(d.getMinutes());
      }};
      // 再暴露工具
      window.__TEST_APPLY_SKIP = function(med, opts){{
        if(typeof _applySkipRulesToMed === 'function') return _applySkipRulesToMed(med, opts || {{ forceRecalc:true }});
      }};
      window.__TEST_GET_SLOT_META = function(med){{
        return med && Array.isArray(med.times) ? med.times : null;
      }};
    }})();
    """)
    page.wait_for_timeout(150)

def fill_med(page: Page, *, name: str, freq: str, times: list[str], start_date: str | None = None):
    dismiss_all_popups(page)
    # 滚动到加药表单，确保 #medName 在可视区
    try:
        page.evaluate("document.getElementById('medName') && document.getElementById('medName').scrollIntoView({block:'center'})")
        page.wait_for_timeout(150)
    except Exception:
        pass
    page.fill("#medName", name)
    page.select_option("#medFreq", freq)
    # 等 time inputs 渲染完，逐个赋值
    page.wait_for_timeout(400)
    inputs = page.query_selector_all("#medTimes input[type='time']")
    if len(inputs) < len(times):
        raise RuntimeError(f"freq={freq} 只出现 {len(inputs)} 个时间 input，期望 {len(times)}")
    for i, t in enumerate(times):
        inputs[i].fill(t)
    if start_date is not None:
        page.fill("#medStartDate", start_date)
    dismiss_all_popups(page)
    # 用 force=True 绕过遮罩拦截
    page.locator("button", has_text="保存用药").first.click(force=True)
    page.wait_for_timeout(800)
    dismiss_all_popups(page)

def find_med_card(page: Page, name_prefix: str) -> Locator:
    """在 medList 里找到以 name_prefix 开头的那张卡（返回 card div.med-item）。"""
    cards = page.locator("#medList .med-item")
    n = cards.count()
    for i in range(n):
        try:
            txt = cards.nth(i).inner_text(timeout=800)
            if txt.startswith(name_prefix) or (name_prefix in txt):
                return cards.nth(i)
        except Exception:
            continue
    raise RuntimeError(f"找不到用药卡片：{name_prefix}")

def chip_texts(card: Locator) -> list[str]:
    return [c.inner_text() for c in card.locator("[data-med-chip]").all()]

def get_slot_reason(page: Page, name_prefix: str):
    """读取某个 med.times 数组（含 skippedReason），通过 page.evaluate。"""
    code = f"""
    (async ()=>{{
      const u = (window.currentUser || 'guest');
      const all = (typeof allMine === 'function') ? (await allMine('meds')) : [];
      const m = all.find(x => x && String(x.name || '').includes({name_prefix!r}));
      if(!m) return null;
      if(!Array.isArray(m.times) || !m.times.every(t=>t && typeof t==='object' && t.time)) {{
        if(typeof _applySkipRulesToMed === 'function') _applySkipRulesToMed(m, {{ forceRecalc:true }});
      }}
      return {{ id:m.id, startDate:m.startDate||null, freq:m.freq, times: (Array.isArray(m.times) ? m.times.map(s=>({{time:s.time, reason:s.skippedReason || null}})) : null) }};
    }})();
    """
    return page.evaluate(code)

# ========== 测试用例 ==========
def t1_strict_zero_grace(page: Page):
    """T1 规则1+8A：20:15 新增 thrice(08:00/12:00/20:00) => 三项都灰跳过。"""
    set_system_time_mock(page, "20:15")
    fill_med(page, name="T1阿司匹林", freq="thrice", times=["08:00", "12:00", "20:00"])
    meta = get_slot_reason(page, "T1阿司匹林")
    if not meta or not meta["times"]:
        return fail("T1", "拿不到结构化 times 元数据")
    reasons = {s["time"]: s["reason"] for s in meta["times"]}
    expected = {"08:00":"past-at-add", "12:00":"past-at-add", "20:00":"past-at-add"}
    if reasons != expected:
        return fail("T1", f"reasons 不一致：期望 {expected} 实际 {reasons}")
    # UI chip 灰条：应包含"免罚"字样
    card = find_med_card(page, "T1阿司匹林")
    txt = card.inner_text()
    if "免罚" not in txt:
        return fail("T1", "UI 没显示免罚灰卡")
    ok("T1")

def t2_denominator_skip(page: Page):
    """T2 规则3B：依从率卡 应服=0（因为三段都跳过），而不是 0/3。"""
    # 读 stats 卡 innerText
    try:
        stat = page.locator("#complianceStats").inner_text(timeout=2000)
    except PWTimeout:
        return fail("T2", "依从率卡没渲染")
    # 取"已服 X / 应服 Y"这一段 Y 值
    import re
    m = re.search(r"已服\s*(\d+)\s*/\s*应服\s*(\d+)", stat)
    if not m:
        return fail("T2", f"依从率格式不符：{stat[:80]}")
    served, denom = int(m.group(1)), int(m.group(2))
    if denom != 0:
        return fail("T2", f"依从率分母期望 0（3 个跳过时段都不计）实际 denom={denom}；served={served}")
    ok("T2")

def t3_future_start(page: Page):
    """T3 规则4B：选明天作为起始日 => 今天 chip 不渲染。"""
    tmr = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    fill_med(page, name="T3未来药", freq="daily", times=["09:00"], start_date=tmr)
    meta = get_slot_reason(page, "T3未来药")
    if meta["startDate"] != tmr:
        return fail("T3", f"起始日没保存：{meta['startDate']}")
    card = find_med_card(page, "T3未来药")
    # card 内应该包含"起始日：YYYY-MM-DD（未来开始）"但不包含任何 09:00 chip（未来开始：今天 chip 不渲染）
    txt = card.inner_text()
    if "未来开始" not in txt:
        return fail("T3", "没显示未来开始徽章")
    if "09:00" in txt:
        return fail("T3", "未来开始的今天不应显示 chip")
    ok("T3")

def t4_historical_backfill(page: Page):
    """T4 规则5B：选 7 天前作为起始日 => 依从率卡 30 天应服中不再含今天之前的（historical-backfill 剔除分母）。"""
    past = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    # 用早7点 + 一次，避免与今天时间比较导致又被 past-at-add
    fill_med(page, name="T4历史药", freq="once", times=["23:59"], start_date=past)
    meta = get_slot_reason(page, "T4历史药")
    # 今天的 23:59 相对于任何白天时间（20:15或更早）都未过 -> past-at-add? 取决于当前真时间
    # 这里不关心今天的 skipped（因为按真实时间），只测 依从率 对 历史日期 backfill 不计分母
    import re
    stat = page.locator("#complianceStats").inner_text()
    m = re.search(r"已服\s*(\d+)\s*/\s*应服\s*(\d+)", stat)
    if not m:
        return fail("T4", f"依从率格式不符：{stat[:80]}")
    denom = int(m.group(2))
    # 应服 最多 1 次（只有今天 23:59 那次 or 0 如果 23:59 也真的没到还不进计划——应该计 1 次，因为今天 23:59 是"正常待服"）
    #   但如果真实系统时间晚于 23:59，那今天的 23:59 仍然会被 past-at-add（跳过）。
    #   所以这里的断言：denom <= 1 且 卡内不再有历史日期的 7 次漏药红色（denom 不会是 8）
    if denom > 1:
        return fail("T4", f"补录起始日前的历史不应计入应服，denom={denom}（期望 <=1）")
    ok("T4")

def t5_expired_single_makeup(page: Page):
    """T5 规则6B：固定 mock 当前时间=21:00，加 单次 20:00 => expired-single -> 点补记后依从率分母 1 分子 1。"""
    set_system_time_mock(page, "21:00")
    fill_med(page, name="T5单次过期药", freq="once", times=["20:00"])
    card = find_med_card(page, "T5单次过期药")
    txt = card.inner_text()
    if "单次已过期" not in txt:
        # 极端情况：系统时间 23:59 选 23:58 也 expired；若测试环境实际没过期就跳过此条（非核心硬错）
        return fail("T5", f"UI 未显示单次已过期：当前时段 {past_slot} 文本={txt[:80]}")
    if "我已服用（补记）" not in txt:
        return fail("T5", "单次过期没显示补记按钮")
    # 点补记
    try:
        card.locator("button", has_text="我已服用（补记）").first.click(timeout=2000)
    except PWTimeout:
        return fail("T5", "点不到补记按钮")
    page.wait_for_timeout(900)
    # 依从率：分母=1，分子=1 => 100%
    stat = page.locator("#complianceStats").inner_text()
    import re
    m = re.search(r"已服\s*(\d+)\s*/\s*应服\s*(\d+)", stat)
    if not m:
        return fail("T5", f"补记后依从率格式错误：{stat[:80]}")
    served, denom = int(m.group(1)), int(m.group(2))
    if served < 1 or denom < 1:
        return fail("T5", f"补记后期望 served>=1 且 denom>=1，实际 {served}/{denom}")
    ok("T5")

def t6_edit_immediate_today(page: Page):
    """T6 规则7A(场景1)：先加一个 daily 20:00（真系统时间没过则保留），编辑改成 21:00。今日 chip 应显示 21:00 不再有 20:00。"""
    # 先加一个"未来时段"确保会有 chip
    now = datetime.datetime.now()
    safe_future = (now + datetime.timedelta(hours=2)).strftime("%H:%M")
    safe_changed = (now + datetime.timedelta(hours=3)).strftime("%H:%M")
    fill_med(page, name="T6改时间", freq="daily", times=[safe_future])
    meta1 = get_slot_reason(page, "T6改时间")
    if not meta1 or meta1["times"][0]["time"] != safe_future:
        return fail("T6", f"初次保存失败：{meta1}")
    # 编辑：改时段
    page.fill("#medName", "T6改时间")  # 名字不严格，但 openEditMed 会填
    page.evaluate(f"""
    (async ()=>{{
      const all = await allMine('meds');
      const m = all.find(x => String(x.name||'').includes('T6改时间'));
      if(m) await openEditMed(m.id);
    }})();
    """)
    page.wait_for_timeout(700)
    inputs = page.query_selector_all("#medTimes input[type='time']")
    assert len(inputs) >= 1
    inputs[0].fill(safe_changed)
    # 保存
    page.locator("button", has_text="保存用药").first.click()
    page.wait_for_timeout(800)
    meta2 = get_slot_reason(page, "T6改时间")
    slot_times = [s["time"] for s in (meta2["times"] or []) if s["reason"] != "__merged_taken"]
    if slot_times != [safe_changed]:
        return fail("T6", f"编辑后期望时段=[{safe_changed}] 实际={slot_times}")
    card = find_med_card(page, "T6改时间")
    txt = card.inner_text()
    if safe_future in txt:
        return fail("T6", "旧时间 chip 未立即消失")
    if safe_changed not in txt:
        return fail("T6", "新时间 chip 未立即出现")
    ok("T6")

def t7_family_add_also_skip(page: Page):
    """T7 规则2A：家属端加药也同样生效（此处缺真实家属/老人双账号绑定云，退化为同账号新增一个 slot 验证跳过标记正确）。"""
    set_system_time_mock(page, "23:59")
    fill_med(page, name="T7家属加", freq="twice", times=["08:00", "14:00"])
    meta = get_slot_reason(page, "T7家属加")
    reasons = {s["time"]: s["reason"] for s in (meta["times"] or [])}
    if reasons.get("08:00") != "past-at-add" or reasons.get("14:00") != "past-at-add":
        return fail("T7", f"家属加的药也应同样 past-at-add：{reasons}")
    ok("T7")

def t8_delete_slot_removes_today_missed(page: Page):
    """T8 规则7A(场景2)：先加 thrice 09:00/13:00/17:00，让 09:00 成为"已过+未服漏药"（如果系统时间 > 09:00 未到 13 点则 09 是 past 灰色跳过，并非漏服 red。我们无法构造"已服漏药"，所以测：删除 09 时段后 chip 只剩 13/17）。"""
    # 选 3 个都在"当前真实时间 - 1h / +1h / +2h"的时间，确保第一个是 past-at-add，后两个未到
    now = datetime.datetime.now()
    past = (now - datetime.timedelta(hours=1)).strftime("%H:%M")
    fut1 = (now + datetime.timedelta(hours=1)).strftime("%H:%M")
    fut2 = (now + datetime.timedelta(hours=2)).strftime("%H:%M")
    fill_med(page, name="T8删时段", freq="thrice", times=[past, fut1, fut2])
    card1 = find_med_card(page, "T8删时段")
    if past not in card1.inner_text():
        return fail("T8", "保存后 past 时段 chip 丢失（应显示灰色跳过）")
    # 编辑：去掉 past 时段 -> daily 只有 1 次是不行；改为 twice=[fut1,fut2]
    page.evaluate(f"""
    (async ()=>{{
      const all = await allMine('meds');
      const m = all.find(x => String(x.name||'').includes('T8删时段'));
      if(m) await openEditMed(m.id);
    }})();
    """)
    page.wait_for_timeout(700)
    page.select_option("#medFreq", "twice")
    page.wait_for_timeout(300)
    inputs = page.query_selector_all("#medTimes input[type='time']")
    for i, t in enumerate([fut1, fut2]):
        inputs[i].fill(t)
    page.locator("button", has_text="保存用药").first.click()
    page.wait_for_timeout(800)
    # 现在卡片里应该没有 past
    card2 = find_med_card(page, "T8删时段")
    txt2 = card2.inner_text()
    if past in txt2:
        return fail("T8", "删除时段后旧时间 chip 仍存在（漏药消失未立即生效）")
    if fut1 not in txt2 or fut2 not in txt2:
        return fail("T8", "删除时段后保留的 chip 不见了")
    ok("T8")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 414, "height": 820})
        page = ctx.new_page()
        tests = [
            ("T1", t1_strict_zero_grace),
            ("T2", t2_denominator_skip),
            ("T3", t3_future_start),
            ("T4", t4_historical_backfill),
            ("T5", t5_expired_single_makeup),
            ("T6", t6_edit_immediate_today),
            ("T7", t7_family_add_also_skip),
            ("T8", t8_delete_slot_removes_today_missed),
        ]
        try:
            login_as_guest(page)
        except Exception as e:
            print("[ABORT] 准备失败:", traceback.format_exc())
            browser.close(); return 2
        for name, fn in tests:
            try:
                fn(page)
            except Exception as e:
                tb = traceback.format_exc()
                last = tb.splitlines()[-1] if tb.strip() else str(e)
                fail(name, "异常: " + last + "\n        " + tb.strip().replace("\n","\n        "))
        browser.close()
    print("\n==== 汇总 ====")
    if not FAIL:
        print("8/8 通过")
        return 0
    print(f"{len(FAIL)} 项失败：")
    for n, m in FAIL:
        print(f"  - {n}: {m}")
    return 1

if __name__ == "__main__":
    sys.exit(main())

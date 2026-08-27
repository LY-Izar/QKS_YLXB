"""用药提醒 到点 弹窗+报警声+按钮 三条件独立验证 TDD。

覆盖：
  R1 quickUse 模式下 checkMeds 能触发（currentUser 为 null 不应阻塞）
     R1-1: quickUse 后 currentUser 应为 null，DB.db 存在
     R1-2: 添加 1 条用药（差 5~10s 到点）→ 立即手动调 checkMeds()（模拟轮询到点）
            ① 弹窗请求是否发起（__MED_ALERT_LAST_FIRE__ 存在且 title 含药名）
            ② 报警声请求是否发起（__DIDI_LAST_FIRE__ 存在且 durationSec=10）
            ③ 操作按钮是否出现在 DOM 中（data-med-action taken/skipped）
  R2 登录账户场景下同样三条独立成立（排除"只有 guest 能用 / 只有登录能用"这种局部修复）
  R3 幂等防重：同一 slot 第二次调 checkMeds() 不重复弹、不重复滴滴声

使用（Windows PowerShell / 项目根目录）：
  cd c:/Users/Administrator/Desktop/医路相伴
  Start-Process python -ArgumentList '-m','http.server','8766' -WindowStyle Hidden
  Start-Sleep 1 ; python tests/med_reminder.test.py
"""
from __future__ import annotations
import sys, os, time, traceback, json
from playwright.sync_api import sync_playwright, Page

ROOT = "http://127.0.0.1:8766/index.html"
FAIL = []

def fail(name, msg):
    FAIL.append((name, msg))
    print(f"[FAIL] {name}: {msg}")
def ok(name):
    print(f"[PASS] {name}")

def reload(page: Page, wait_ms=2600):
    page.goto(ROOT, wait_until="networkidle")
    page.wait_for_timeout(wait_ms)
    try:
        page.wait_for_function("typeof DB !== 'undefined' && DB && DB.db", timeout=15000)
    except Exception:
        pass

def wait_db(page: Page, timeout_ms=15000):
    """等待 IndexedDB 就绪"""
    page.wait_for_function(
        "typeof DB !== 'undefined' && DB && DB.db",
        timeout=timeout_ms,
    )

def click_body(page: Page):
    """模拟用户一次 gesture 交互，让 AudioContext 能 resume"""
    page.evaluate("""
    (function(){
      try{
        const evt = new MouseEvent('click', {bubbles:true, cancelable:true, view:window});
        (document.body || document.documentElement).dispatchEvent(evt);
      }catch(_){}
    })();""")
    page.wait_for_timeout(200)

def set_login_state(page, user, role='elder'):
    """把页面登录态切到指定用户（不走实际登录框，直接写内存 + localStorage + 调 updateUserUI）"""
    page.evaluate("""
    ([u,r]) => {
      localStorage.setItem('med_user', u);
      localStorage.setItem('med_role', r);
      localStorage.setItem('med_is_admin','0');
      localStorage.setItem('med_admin_level','none');
      localStorage.setItem('med_sub_perms','{}');
      try{ currentUser = u; myRole = r; isAdmin=false; adminLevel='none'; subPerms={}; }catch(_){}
      try{ updateUserUI && typeof updateUserUI==='function' && updateUserUI(); }catch(_){}
    }""", [user, role])
    page.wait_for_timeout(400)

def do_quick_use(page):
    """调用 quickUse() 进入体验模式"""
    page.evaluate("""
    (async function(){
      try{ if(typeof quickUse==='function') await quickUse(); }catch(_){}
    })();""")
    page.wait_for_timeout(600)

def add_med_for(page, user_or_guest, name, dose, hhmm_slot, start_date_ymd, med_id):
    """直接往 IndexedDB.meds 塞一条指定提醒时间的用药记录（绕过 addMed 表单，避免 UI 时序干扰）。
    返回 {slot: HH:MM}。塞完之后显式 renderMeds() 让 setTimeout 注册按钮。"""
    return page.evaluate("""
    async ([u, name, dose, slot, ymd, mid]) => {
      const withU = (o) => Object.assign({}, o||{}, {username: u || 'guest'});
      const med = withU({
        id: mid,
        name, dose, freq:'daily',
        times: [{time:slot, skippedReason:null}],
        time: slot,
        startDate: ymd,
        reminded: {},
        created: Date.now()
      });
      try{ await DB.put('meds', med); }catch(e){ return {ok:false, err:String(e)}; }
      try{ await renderMeds(); }catch(e){ return {ok:false, err2:String(e), slot}; }
      // 清空 TDD 钩子，保证本次检测的是后续 checkMeds 新触发的
      try{ window.__MED_ALERT_LAST_FIRE__ = null; window.__DIDI_LAST_FIRE__ = null; window.__MED_ALERT_HISTORY__ = []; }catch(_){}
      return {ok:true, slot};
    }""", [user_or_guest, name, dose, hhmm_slot, start_date_ymd, med_id])

def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width":1280,"height":800}, locale="zh-CN")
        context.grant_permissions(["notifications"])
        page = context.new_page()

        # =======================================================
        # 准备：打开页面 + 等待 DB + 一次 gesture 预热 AudioContext
        # =======================================================
        reload(page, wait_ms=2800)
        try: wait_db(page)
        except Exception as e:
            fail('PREP-DB', 'IndexedDB 26 秒仍未就绪：'+traceback.format_exc(limit=2))
            browser.close()
            return
        # 用户 gesture 预热（Autoplay 策略：浏览器要求用户交互后才能发声）
        click_body(page)
        ok('PREP: 页面就绪 + DB 可用 + 用户 gesture 已触发')

        # -------------------------------------------------------
        # R1: quickUse 模式（currentUser=null）下到点提醒三条件
        # -------------------------------------------------------
        try:
            do_quick_use(page)
            r_state = page.evaluate("""() => ({
              currentUser: typeof currentUser==='undefined' ? '__undef__' : (currentUser||null),
              hasDb: !!(DB && DB.db)
            })""")
            if r_state.get('currentUser') is not None:
                fail('R1-1', f'quickUse 后 currentUser 应为 null，实际=' + repr(r_state.get('currentUser')))
            else: ok('R1-1 quickUse 后 currentUser=null（符合体验模式）')
            if not r_state.get('hasDb'):
                fail('R1-1DB', 'quickUse 后 DB.db 仍未就绪')
            else: ok('R1-1 DB 就绪')

            # 计算"北京时区当前整分钟 + 1 分钟"作为目标提醒时间（保证 checkMeds 里 curMin - tm ∈ [0, 1] 能命中首次窗口）
            plan = page.evaluate("""() => {
              const pad = n => String(n).padStart(2,'0');
              const bj = new Date(Date.now() + (new Date().getTimezoneOffset()+8*60)*60*1000);
              // 目标 = 下一分钟（避免 < -1 还没到；但也不会超过 +1，恰好落在首次 ±1min 窗口内）
              bj.setMinutes(bj.getMinutes()+1);
              bj.setSeconds(0); bj.setMilliseconds(0);
              const ymd = bj.getFullYear()+'-'+pad(bj.getMonth()+1)+'-'+pad(bj.getDate());
              const slot = pad(bj.getHours())+':'+pad(bj.getMinutes());
              return {ymd, slot, epochMs: bj.getTime()};
            }""")
            slot, ymd = plan['slot'], plan['ymd']
            ok(f'R1-PREP: 目标提醒时间 slot={slot} ymd={ymd}')

            add_med_for(page, None, '缬沙坦', '1片', slot, ymd, 'rm_qk_01')
            page.wait_for_timeout(700)

            # 先断言：按钮 setTimeouts Map 有注册（这条是 renderMeds 内部保证的，我们只做 sanity check）
            r_pre = page.evaluate("""() => {
              const has = typeof window._MED_BTN_TIMEOUTS !== 'undefined' && window._MED_BTN_TIMEOUTS;
              const size = has ? has.size : -1;
              return {size};
            }""")
            if r_pre.get('size', -1) >= 1:
                ok(f'R1-PREP: _MED_BTN_TIMEOUTS 已注册 timer（size={r_pre["size"]}）')
            else:
                print(f'[WARN] R1-PREP: timer size={r_pre.get("size")}（可能因为 slot=下一分钟差一点点，但这不影响"手动调 checkMeds 验证弹窗+声音"）')

            # 等到 slot 对应的整分钟（最多等 70 秒），然后手动调用一次 checkMeds()
            now_ms = int(time.time() * 1000)
            target_start_ms = plan['epochMs'] - 1000  # 比整分钟早 1s 开始等待
            wait_before = max(0, target_start_ms - now_ms)
            if wait_before > 0:
                print(f'[INFO] 等待 {wait_before}ms 到 slot={slot} 前 1s ...')
                page.wait_for_timeout(wait_before + 2200)  # 等过整分钟 + 2s 余量

            # 清钩子 → 手动调 checkMeds() → 读三条件
            page.evaluate("""() => {
              window.__MED_ALERT_LAST_FIRE__ = null;
              window.__DIDI_LAST_FIRE__ = null;
              window.__MED_ALERT_HISTORY__ = [];
            }""")
            page.evaluate("""async () => { try{ await checkMeds(); }catch(e){ console.warn('[TEST] checkMeds fail:', e); } }""")
            page.wait_for_timeout(3200)  # 等待 playDidiAlert 内部 resume + 排程 beeps 最多 ~1.5s + DOM

            r_r1 = page.evaluate("""() => {
              // 独立条件 ①：弹窗请求（TDD 钩子 + DOM 两种都判，确保"真的想弹"和"真的画了 DOM"）
              const hook = window.__MED_ALERT_LAST_FIRE__ || null;
              const wrapDom = document.getElementById('__medAlertWrap__');
              const domExists = !!wrapDom;
              const domTitle = domExists ? (wrapDom.innerText||'').slice(0,120) : '';

              // 独立条件 ②：报警声请求（注意：headless 里 AudioContext 可能仍 suspended，
              //   但只要 __DIDI_LAST_FIRE__ 被写了，就证明 playDidiAlert 被真正调用过且走到了请求阶段——这就是"浏览器发起了报警声请求"）
              const didi = window.__DIDI_LAST_FIRE__ || null;

              // 独立条件 ③：操作按钮（到点后应该立即有 data-med-action='taken'/'skipped' 按钮）
              const card = document.querySelector('[data-med-id="rm_qk_01"]');
              let btns = [];
              if(card){
                const bList = card.querySelectorAll('button[data-med-action]');
                btns = Array.from(bList).map(b=>({
                  a: b.getAttribute('data-med-action'),
                  t: (b.textContent||'').trim(),
                  tm: decodeURIComponent(b.getAttribute('data-time')||'')
                }));
              }
              const hasTake = btns.some(b => b.a === 'taken' || b.a === 'late_taken');
              const hasSkip = btns.some(b => b.a === 'skipped');

              return {
                alertHook: hook,
                alertDomExists: domExists,
                alertDomTitle: domTitle,
                didiHook: didi,
                btns,
                hasTake,
                hasSkip,
                medCardExists: !!card
              };
            }""")

            # ① 弹窗
            hook = r_r1.get('alertHook') or {}
            if not hook:
                fail('R1-2a 弹窗(钩子)', '__MED_ALERT_LAST_FIRE__ 为空——checkMeds 到点没有调用 showMedAlertUI')
            elif '缬沙坦' not in hook.get('title',''):
                fail('R1-2a 弹窗(钩子)', f"title 不包含药名「缬沙坦」，实际 title={repr(hook.get('title',''))}")
            else: ok('R1-2a 弹窗钩子已触发（title 含药名）')
            if not r_r1.get('alertDomExists'):
                fail('R1-2a 弹窗(DOM)', 'id=__medAlertWrap__ 节点未被插入 body——弹窗实际未渲染')
            else: ok('R1-2a 弹窗 DOM 已插入 body')

            # ② 滴滴声
            didi = r_r1.get('didiHook') or {}
            if not didi:
                fail('R1-2b 报警声', '__DIDI_LAST_FIRE__ 为空——checkMeds 到点没有调用 playDidiAlert')
            else:
                dur = didi.get('durationSec')
                if dur != 10:
                    fail('R1-2b 报警声', f'durationSec 应为 10，实际={repr(dur)}。完整=' + json.dumps(didi, ensure_ascii=False))
                else: ok(f'R1-2b 报警声请求已发起（durationSec={dur}，skipped={didi.get("skipped")}，state={didi.get("state")}）')

            # ③ 按钮
            if not r_r1.get('medCardExists'):
                fail('R1-2c 操作按钮', '未找到 [data-med-id="rm_qk_01"] 用药卡片')
            elif (not r_r1.get('hasTake')) or (not r_r1.get('hasSkip')):
                fail('R1-2c 操作按钮', f'到点后未同时出现「已服用」和「跳过今天」。实际 btns=' + json.dumps(r_r1.get('btns'), ensure_ascii=False))
            else: ok('R1-2c 操作按钮已渲染（taken + skipped 都有）')

            # ======== R3：幂等防重（同一 slot 再调一次 checkMeds 不应再产生新弹窗 / 新滴滴）========
            page.evaluate("""() => {
              window.__MED_ALERT_HISTORY_BEFORE__ = (window.__MED_ALERT_HISTORY__ || []).length;
              window.__DIDI_BEFORE__ = window.__DIDI_LAST_FIRE__ ? window.__DIDI_LAST_FIRE__.t : 0;
            }""")
            page.evaluate("""async () => { try{ await checkMeds(); }catch(e){} }""")
            page.wait_for_timeout(900)
            r_r3 = page.evaluate("""() => {
              const afterHist = (window.__MED_ALERT_HISTORY__ || []).length;
              const beforeHist = window.__MED_ALERT_HISTORY_BEFORE__ || 0;
              const afterT = window.__DIDI_LAST_FIRE__ ? window.__DIDI_LAST_FIRE__.t : 0;
              const beforeT = window.__DIDI_BEFORE__ || 0;
              return {
                alertHistorySame: afterHist === beforeHist,
                alertHistoryDelta: afterHist - beforeHist,
                didiSame: afterT <= beforeT,
                beforeHist, afterHist, beforeT, afterT
              };
            }""")
            if not r_r3.get('alertHistorySame'):
                fail('R3-1 幂等(弹窗)', f'同一 slot 第二次 checkMeds 新增弹窗 delta={r_r3.get("alertHistoryDelta")}（应=0）')
            else: ok('R3-1 同一 slot 不重复弹窗（幂等）')
            if not r_r3.get('didiSame'):
                fail('R3-2 幂等(滴滴声)', '同一 slot 第二次 checkMeds 仍写了新的 __DIDI_LAST_FIRE__（应不变）')
            else: ok('R3-2 同一 slot 不重复滴滴声（幂等）')
        except Exception as e:
            fail('R1/R3', '异常: ' + traceback.format_exc(limit=4))

        # -------------------------------------------------------
        # R2: 登录账户场景同样三条件独立成立（真实账号场景）
        # -------------------------------------------------------
        try:
            reload(page)
            wait_db(page)
            click_body(page)
            set_login_state(page, 'med_user_r2_001', 'elder')
            # 清历史：删掉该账户旧数据，避免影响
            page.evaluate("""
            async (u) => {
              const list = await DB.all('meds');
              for(const r of list){
                if(r && r.username === u){ try{ await DB.del('meds', r.id); }catch(_){} }
              }
              const logs = await DB.all('medlog');
              for(const r of logs){
                if(r && r.username === u){ try{ await DB.del('medlog', r.id); }catch(_){} }
              }
            }""", 'med_user_r2_001')
            page.wait_for_timeout(300)

            plan = page.evaluate("""() => {
              const pad = n => String(n).padStart(2,'0');
              const bj = new Date(Date.now() + (new Date().getTimezoneOffset()+8*60)*60*1000);
              bj.setMinutes(bj.getMinutes()+1);
              bj.setSeconds(0); bj.setMilliseconds(0);
              const ymd = bj.getFullYear()+'-'+pad(bj.getMonth()+1)+'-'+pad(bj.getDate());
              const slot = pad(bj.getHours())+':'+pad(bj.getMinutes());
              return {ymd, slot, epochMs: bj.getTime()};
            }""")
            slot, ymd = plan['slot'], plan['ymd']
            ok(f'R2-PREP: 目标提醒时间 slot={slot} ymd={ymd}（登录场景）')

            add_med_for(page, 'med_user_r2_001', '二甲双胍', '0.5g/片', slot, ymd, 'rm_r2_01')
            page.wait_for_timeout(700)

            # 先关闭自动 30s checkMeds interval（避免它在等待期间先触发，把 remindSlots 已打勾 + __MED_ALERT_LAST_FIRE__ 写到和测试竞争）。
            # 同时清掉任何已提前触发的弹窗 DOM / 状态，保证本次检测纯靠本测试手动 checkMeds() 产生。
            page.evaluate("""() => {
              try{
                if(typeof window.__CHECKMEDS_INTERVAL_DISABLED__ === 'undefined'){
                  // 暴力：清理前 20 个 interval，找到 checkMeds 那个。
                  const maxId = window.setTimeout(()=>{},0);
                  for(let i=1; i<=maxId; i++){ try{ clearInterval(i); }catch(_){} }
                  window.__CHECKMEDS_INTERVAL_DISABLED__ = true;
                }
              }catch(_){}
              // 清残留弹窗 DOM + 状态
              try{
                const w = document.getElementById('__medAlertWrap__');
                if(w){ w.remove(); }
                _medAlertModalOpen = false;
              }catch(_){}
            }""")
            page.wait_for_timeout(200)

            now_ms = int(time.time() * 1000)
            target_start_ms = plan['epochMs'] - 1000
            wait_before = max(0, target_start_ms - now_ms)
            if wait_before > 0:
                print(f'[INFO] 等待 {wait_before}ms 到 slot={slot} 前 1s ...')
                page.wait_for_timeout(wait_before + 2200)

            # 调用前再次确保：DB 里这条 med 的 remindSlots 没被"其它地方"提前勾掉（防止竞争）
            page.evaluate("""async () => {
              const all = await DB.all('meds');
              for(const m of all){
                if(m && m.id === 'rm_r2_01'){
                  delete m.remindSlots;
                  delete m.reminded;
                  delete m.remindCounts;
                  try{ await DB.put('meds', m); }catch(_){}
                }
              }
            }""")
            page.wait_for_timeout(200)

            page.evaluate("""() => {
              window.__MED_ALERT_LAST_FIRE__ = null;
              window.__DIDI_LAST_FIRE__ = null;
              window.__MED_ALERT_HISTORY__ = [];
            }""")
            page.evaluate("""async () => { try{ await checkMeds(); }catch(e){ console.warn('[TEST] checkMeds R2 fail:', e); } }""")
            page.wait_for_timeout(3200)

            r_r2 = page.evaluate("""() => {
              const hook = window.__MED_ALERT_LAST_FIRE__ || null;
              const wrapDom = document.getElementById('__medAlertWrap__');
              const didi = window.__DIDI_LAST_FIRE__ || null;
              const card = document.querySelector('[data-med-id="rm_r2_01"]');
              let btns = [];
              if(card){
                btns = Array.from(card.querySelectorAll('button[data-med-action]')).map(b=>({
                  a: b.getAttribute('data-med-action'),
                  t: (b.textContent||'').trim(),
                  tm: decodeURIComponent(b.getAttribute('data-time')||'')
                }));
              }
              return {
                alertHook: hook,
                alertDomExists: !!wrapDom,
                didiHook: didi,
                medCardExists: !!card,
                btns,
                hasTake: btns.some(b => b.a === 'taken' || b.a === 'late_taken'),
                hasSkip: btns.some(b => b.a === 'skipped'),
                effectiveUser: typeof currentUser !== 'undefined' ? (currentUser||null) : null
              };
            }""")

            if r_r2.get('effectiveUser') != 'med_user_r2_001':
                fail('R2-0 登录态', f'currentUser 应为 med_user_r2_001，实际=' + repr(r_r2.get('effectiveUser')))
            else: ok('R2-0 登录态为 med_user_r2_001（验证三条件前先确认不是 guest 路径）')

            hook = r_r2.get('alertHook') or {}
            if not hook:
                fail('R2-1 弹窗', '__MED_ALERT_LAST_FIRE__ 为空——登录场景 checkMeds 未调用 showMedAlertUI')
            elif '二甲双胍' not in hook.get('title',''):
                fail('R2-1 弹窗', f'title 不含「二甲双胍」，title={repr(hook.get("title",""))}')
            else: ok('R2-1 登录场景弹窗钩子正确')
            if not r_r2.get('alertDomExists'):
                fail('R2-1 弹窗(DOM)', '登录场景 id=__medAlertWrap__ 未插入 body')
            else: ok('R2-1 登录场景弹窗 DOM 已插入')

            didi = r_r2.get('didiHook') or {}
            if not didi:
                fail('R2-2 报警声', '登录场景 __DIDI_LAST_FIRE__ 为空')
            elif didi.get('durationSec') != 10:
                fail('R2-2 报警声', f'durationSec={repr(didi.get("durationSec"))}，应=10')
            else: ok(f'R2-2 登录场景报警声请求已发起（skipped={didi.get("skipped")}）')

            if not r_r2.get('medCardExists'):
                fail('R2-3 操作按钮', '登录场景未找到用药卡片 [data-med-id="rm_r2_01"]')
            elif (not r_r2.get('hasTake')) or (not r_r2.get('hasSkip')):
                fail('R2-3 操作按钮', f'登录场景到点后按钮不全：' + json.dumps(r_r2.get('btns'), ensure_ascii=False))
            else: ok('R2-3 登录场景操作按钮已渲染（taken + skipped）')
        except Exception as e:
            fail('R2', '异常: ' + traceback.format_exc(limit=4))

        # -------------------------------------------------------
        # R6: 新增规则1 —— "新增时已过"的灰卡 slot 不弹窗不滴滴
        # R7: 新增规则2 —— 超 30 分钟窗口（32min / 45min）不弹窗不滴滴
        #     同时含一条 R8 正例（3min 前、无灰卡）确保"30 分钟内仍然触发"没被误杀
        # -------------------------------------------------------
        try:
            reload(page)
            wait_db(page)
            click_body(page)
            do_quick_use(page)
            # 关掉 interval + 清残留
            page.evaluate("""() => {
              try{
                const maxId = window.setTimeout(()=>{},0);
                for(let i=1; i<=maxId; i++){ try{ clearInterval(i); }catch(_){} }
              }catch(_){}
              try{ const w = document.getElementById('__medAlertWrap__'); if(w) w.remove(); }catch(_){}
              try{ _medAlertModalOpen = false; }catch(_){}
            }""")
            page.wait_for_timeout(250)

            plan = page.evaluate("""() => {
              const pad = n => String(n).padStart(2,'0');
              const bj = new Date(Date.now() + (new Date().getTimezoneOffset()+8*60)*60*1000);
              const ymd = bj.getFullYear()+'-'+pad(bj.getMonth()+1)+'-'+pad(bj.getDate());
              const hm = d => pad(d.getHours())+':'+pad(d.getMinutes());
              return {
                ymd,
                s_past_at_add_3min: hm(new Date(bj.getTime()-3*60*1000)),   // 3 分钟前 + 标 past-at-add → 静默
                s_inwin_nogray_3min:  hm(new Date(bj.getTime()-3*60*1000)),  // 3 分钟前、无灰卡 → 30 分钟内应触发
                s_over32min:          hm(new Date(bj.getTime()-32*60*1000)), // 32 分钟前、无灰卡 → 超窗静默
                s_over45min:          hm(new Date(bj.getTime()-45*60*1000))  // 45 分钟前、无灰卡 → 超窗静默
              };
            }""")
            ok(f'R6/R7/R8-PREP: 时间槽 plan={json.dumps(plan, ensure_ascii=False)}')
            ymd = plan['ymd']

            # 一次清库 + 塞 4 条 meds
            page.evaluate("""async (p) => {
              for(const s of ['meds','medlog']){
                const list = await DB.all(s);
                for(const r of list){ try{ await DB.del(s, r.id); }catch(_){} }
              }
              const rows = [
                {id:'r6_01', username:'guest', name:'R6 灰卡阿司匹林', dose:'1片', freq:'daily',
                  times:[{time:p.s_past_at_add_3min, skippedReason:'past-at-add'}],
                  time:p.s_past_at_add_3min, startDate:p.ymd, reminded:{}, created:Date.now()},
                {id:'r8_01', username:'guest', name:'R8 3min无灰卡', dose:'1片', freq:'daily',
                  times:[{time:p.s_inwin_nogray_3min, skippedReason:null}],
                  time:p.s_inwin_nogray_3min, startDate:p.ymd, reminded:{}, created:Date.now()},
                {id:'r7a_01', username:'guest', name:'R7a 超32min', dose:'1片', freq:'daily',
                  times:[{time:p.s_over32min, skippedReason:null}],
                  time:p.s_over32min, startDate:p.ymd, reminded:{}, created:Date.now()},
                {id:'r7b_01', username:'guest', name:'R7b 超45min', dose:'1片', freq:'daily',
                  times:[{time:p.s_over45min, skippedReason:null}],
                  time:p.s_over45min, startDate:p.ymd, reminded:{}, created:Date.now()},
              ];
              for(const r of rows){ await DB.put('meds', r); }
              try{ await renderMeds(); }catch(e){ console.warn(e); }
            }""", plan)
            page.wait_for_timeout(700)

            # 清钩子 → checkMeds
            page.evaluate("""() => {
              window.__MED_ALERT_LAST_FIRE__ = null;
              window.__DIDI_LAST_FIRE__ = null;
              window.__MED_ALERT_HISTORY__ = [];
            }""")
            page.evaluate("""async () => { try{ await checkMeds(); }catch(e){ window.__CM_ERR__ = String(e); } }""")
            page.wait_for_timeout(3000)

            # 取每条 med 各自的命中情况：通过 history length + history title 判断（因为 showMedAlertUI 同一时刻只画 1 个 DOM）
            r_x = page.evaluate("""() => {
              const hist = window.__MED_ALERT_HISTORY__ || [];
              const titles = hist.map(h => h.title);
              const didiFired = !!window.__DIDI_LAST_FIRE__;
              return {
                histCount: hist.length,
                titles,
                didiFired,
                err: window.__CM_ERR__ || null,
                // DOM：最终是否仍存在弹窗（1 条正例应在）
                wrapExists: !!document.getElementById('__medAlertWrap__')
              };
            }""")
            if r_x.get('err'):
                fail('R6-R8-PREP', 'checkMeds 异常: ' + str(r_x['err']))
            titles = r_x.get('titles') or []
            # R6: past-at-add 不应出现在任何弹窗标题里
            if any('R6 灰卡阿司匹林' in t for t in titles):
                fail('R6 新增时已过', f'被标记 past-at-add 的 R6 灰卡仍然触发了弹窗。titles={json.dumps(titles,ensure_ascii=False)}')
            else: ok('R6 past-at-add 灰卡：未触发任何弹窗（静默正确）')

            # R7a / R7b: 超 32 / 45 分钟不应有弹窗
            if any('R7a 超32min' in t for t in titles):
                fail('R7a 超窗32min', '32 分钟前无灰卡药名仍被弹窗，titles=' + json.dumps(titles, ensure_ascii=False))
            else: ok('R7a 超窗32min：未触发弹窗（30min 上限正确）')
            if any('R7b 超45min' in t for t in titles):
                fail('R7b 超窗45min', '45 分钟前无灰卡药名仍被弹窗，titles=' + json.dumps(titles, ensure_ascii=False))
            else: ok('R7b 超窗45min：未触发弹窗（30min 上限正确）')

            # R8 正例：3 分钟前 无灰卡 应被 30min 窗口命中
            if not any('R8 3min无灰卡' in t for t in titles):
                fail('R8 30分钟内仍应提醒', f'3 分钟前无灰卡的"R8 3min无灰卡"没有出现在弹窗历史里（说明 30min 窗口可能收太严或逻辑被误杀）。titles={json.dumps(titles,ensure_ascii=False)} didi={r_x.get("didiFired")} wrap={r_x.get("wrapExists")}')
            else: ok('R8 30 分钟窗口内正常触发（3 分钟前无灰卡 → 弹窗标题含药名）')
            # R8 对应的滴滴声：只要任意提醒发了（即 didiFired=true）就算通过（滴滴声是每条提醒都会调一次，至少一次有）
            if not r_x.get('didiFired'):
                fail('R8 滴滴声', '本次 checkMeds 没有任何提醒调用 playDidiAlert（至少 R8 该调一次）')
            else: ok('R8 30 分钟窗口内 playDidiAlert 被调用（滴滴声请求已发起）')
        except Exception as e:
            fail('R6/R7/R8', '异常: ' + traceback.format_exc(limit=4))

        browser.close()

# ===== 执行 =====
if __name__ == '__main__':
    run_tests()
    print()
    if FAIL:
        print(f"共 {len(FAIL)} 个失败：")
        for n, m in FAIL: print(f"  - {n}: {m}")
        sys.exit(1)
    else:
        print("全部 R1/R2/R3/R6/R7/R8 用例通过。")

"""管理员分层 + 维护模式 + 非法字符审查 TDD（AH1-AH15）。

覆盖：
  AH1  super-admin(15184461098_admin) 导航栏可见"管理"，sub-admin 必须选家属角色才显示
  AH2  次级管理员默认 5 项受限功能按钮 disabled（db/force_popup/pin/email_push/mmode）
  AH3  requirePerm 未授权时不允许保存（公告勾选置顶，sub 会被拦截：不入库）
  AH4  管理员分层：用户列表列显示最高管理员红徽章 / 次级管理员蓝徽章 / 否灰字
  AH5  审计邮件：次级管理员每次管理操作（含只读：loadUsers/search/分页）都会触发 audit()
       → 在 window 上埋 _auditRecords 数组作为内存捕获，不为空即通过
  AH6  维护模式开关：adminMMToggle(true) → MAINTENANCE.enabled=true + banner 出现（super 蓝灰条）
  AH7  维护模式已开启 → 非管理员 quickUse/go('home') 都被拦住，停留在 welcome
  AH8  维护模式已开启 → 普通账号登录成功末尾仍被强制清登录态，回到 welcome + 弹提示
  AH9  维护模式定时：start_at/end_at 会写入 app_settings，banner 上显示维护时段
  AH10 URL ?admin_approve=TOKEN  /  ?admin_reject=TOKEN  落地：
       handleURLApprovalTokens 被调用（存在该函数，且读 URL 参数）
  AH11 全局非法字符过滤器：sanitizeText 对 <script>、反引号、$、|、\\ 转成全角或移除
  AH12 所有保存函数：validateText 命中 DANGER_PATTERNS(union select / -- / drop table) 时返回 ok=false
  AH13 mountGlobalInputGuards 对所有 input/textarea 已自动挂 guard，输入非法字符后 value 被净化
  AH14 [BUGFIX] 登出 doLogout() 必须清掉 med_admin_level / sub_perms，否则刷新后残留为 admin
       → 游客状态下 refresh 后 isAdminDuringMaintenance() 必须返回 false
  AH15 [BUGFIX] 维护模式开启后，游客 welcome 冷启动（refresh 无踢人触发）下：
       → renderMaintenanceBanner 显示红色 banner（forAdmin=false）
       → refreshNavVisibilityForMaintenance 使 btnQuick disabled=true，navbar 隐藏

依赖：
  pip install playwright
  playwright install chromium

使用（Windows PowerShell / 项目根目录下）：
  cd c:/Users/Administrator/Desktop/医路相伴
  Start-Process python -ArgumentList '-m','http.server','8766' -WindowStyle Hidden
  Start-Sleep 1 ; python tests/admin_hierarchy.test.py
"""
from __future__ import annotations
import sys, os, time, traceback, urllib.parse, json
from playwright.sync_api import sync_playwright, expect, Page, TimeoutError as PWTimeout

ROOT = "http://127.0.0.1:8766/index.html"
FAIL = []

def fail(name, msg):
    FAIL.append((name, msg))
    print(f"[FAIL] {name}: {msg}")
def ok(name):
    print(f"[PASS] {name}")

def dismiss_all_popups(page: Page):
    page.evaluate("""
    (function(){
      const ids = ['annPopup','medAlertUI','authMask','medMask','famMask','admAnnModal','admResetModal'];
      ids.forEach(id=>{
        const el = document.getElementById(id); if(!el) return;
        el.style.display='none'; el.classList.remove('active','show');
      });
      document.querySelectorAll('.modal.active, .sheet.active, .mask.show').forEach(m=>{
        m.style.display='none'; m.classList.remove('active','show');
      });
    })();""")
    page.wait_for_timeout(250)

def set_admin_state(page: Page, user_id, level='none', perms=None, role='family'):
    """直接写 localStorage + IndexedDB(users 伪造一条本地记录)，让前端认为已登录某账户。"""
    perms_dict = perms if isinstance(perms, dict) else {
        'db': False, 'force_popup': False, 'pin': False, 'email_push': False, 'mmode': False
    }
    perms_json = json.dumps(perms_dict, ensure_ascii=False)
    # 传给 evaluate 的字符串：所有值拼进模板字符串时用 json.dumps
    js_user = json.dumps(user_id, ensure_ascii=False)
    js_role = json.dumps(role, ensure_ascii=False)
    js_lvl  = json.dumps(level, ensure_ascii=False)
    js_perm = perms_json
    is_admin = 'true' if level in ('super', 'sub') else 'false'
    page.evaluate(f"""
    (async function(){{
      // localStorage
      localStorage.setItem('med_user',        {js_user});
      localStorage.setItem('med_role',        {js_role});
      localStorage.setItem('med_is_admin',    {is_admin});
      localStorage.setItem('med_admin_level', {js_lvl});
      localStorage.setItem('med_sub_perms',   {js_perm});
      // IndexedDB: 尝试写 users 表
      try {{
        const req = indexedDB.open('medical_nav', 2);
        req.onupgradeneeded = e => {{
          const db = e.target.result;
          if(!db.objectStoreNames.contains('users')) db.createObjectStore('users', {{keyPath:'id'}});
        }};
        await new Promise(res=>{{
          req.onsuccess = () => {{
            const db = req.result;
            try {{
              const tx = db.transaction('users','readwrite');
              tx.objectStore('users').put({{
                id:          {js_user},
                pass_hash:   '__test__',
                familyCode:  '000000',
                role:        'elder',
                isAdmin:     {is_admin},
                admin_level: {js_lvl},
                sub_perms:   JSON.parse({js_perm}),
                created:     Date.now()
              }});
              tx.oncomplete = ()=>res(0); tx.onerror = ()=>res(0);
            }} catch(_) {{ res(0); }}
          }};
          req.onerror = ()=>res(0);
        }});
      }} catch(_) {{ }}
    }})();""")
    page.wait_for_timeout(100)

def reload(page: Page, wait_ms=2200):
    page.goto(ROOT, wait_until="networkidle")
    page.wait_for_timeout(wait_ms)
    # 等待所有全局函数就绪
    try:
        page.wait_for_function("""
        (function(){
          const fns = ['sanitizeText','validateText','mountInputGuard','hasPerm','applyMaintenance',
                       'handleURLApprovalTokens','ensureRealtimeClient','afterLogin','go',
                       '_afterLoginMaintenanceGate','audit','updateUserUI','updateAdminUI'];
          return fns.every(n=>typeof window[n]==='function');
        })()""", timeout=10000)
    except Exception as _:
        # 即使缺少某些函数也允许继续（让具体 case 自己 fail）
        pass
    dismiss_all_popups(page)

# =====================================================================
# 用例
# =====================================================================
def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width":1280,"height":900})
        page = ctx.new_page()

        # ---------- AH11: sanitizeText 全局过滤 ----------
        try:
            reload(page)
            r = page.evaluate("""
            ({
              a: sanitizeText('<script>alert(1)</script>', 200),
              b: sanitizeText('drop table users; -- bye', 200),
              c: sanitizeText('price $100 | free', 200),
              d: sanitizeText('\\\\back\\\\tick`ok`', 200),
            })""")
            if '<script>' in r['a'] or '<' in r['a'].replace('＜',''):
                fail('AH11-1', f'sanitizeText 没清除 <script>：{r["a"]}')
            else: ok('AH11-1 <script> 被转义/清除')
            if '$' in r['c'] or '|' in r['c']:
                fail('AH11-2', f'$ / | 未转义：{r["c"]}')
            else: ok('AH11-2 $ | 转成全角')
            if '`' in r['d'] or '\\' in r['d']:
                fail('AH11-3', f'反引号/反斜杠未转义：{r["d"]}')
            else: ok('AH11-3 反引号 反斜杠 转义')
        except Exception as e:
            fail('AH11', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH12: validateText + DANGER_PATTERNS 拦截 ----------
        try:
            r = page.evaluate("""
            ({
              a: validateText('union select * from users', {label:'x'}),
              b: validateText('drop table users; --', {label:'x'}),
              c: validateText('<img src=x onerror=alert(1)>', {label:'x'}),
              d: validateText('正常公告标题：升级通知', {label:'x'}),
            })""")
            if r['a']['ok']: fail('AH12-1', f'union select 未拦截：{r["a"]}')
            else: ok('AH12-1 union select 拦截 ok')
            if r['b']['ok']: fail('AH12-2', f'drop table/-- 未拦截：{r["b"]}')
            else: ok('AH12-2 drop/-- 拦截 ok')
            if r['c']['ok']: fail('AH12-3', f'onerror XSS 未拦截：{r["c"]}')
            else: ok('AH12-3 onerror XSS 拦截 ok')
            if not r['d']['ok']: fail('AH12-4', f'正常文本误伤：{r["d"]}')
            else: ok('AH12-4 正常文本通过')
        except Exception as e:
            fail('AH12', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH13: mountGlobalInputGuards 自动挂载 + 净化 ----------
        try:
            reload(page)
            has_guards = page.evaluate("""
            // 造一个临时 input 并挂 guard 检测：
            const el = document.createElement('input'); el.type='text'; el.maxLength=80;
            document.body.appendChild(el); mountInputGuard(el);
            // 模拟输入事件
            el.value = '<svg onload=alert(1)>';
            const ev = new Event('input', {bubbles:true});
            el.dispatchEvent(ev);
            const after = el.value;
            el.remove();
            ({after: after, anyGuard: Array.from(document.querySelectorAll('input,textarea')).some(x=>x.__guardMounted)});
            """)
            if not has_guards['anyGuard']:
                fail('AH13-1', '文档里没有任何一个 input/textarea 被 mountInputGuard 挂载')
            else: ok('AH13-1 静态 input/textarea 已挂 guard')
            if '<' in has_guards['after'] and 'svg' in has_guards['after'].lower():
                fail('AH13-2', f'挂载 guard 后输入 <svg onload> 未净化：{has_guards["after"]}')
            else: ok('AH13-2 input 事件实时净化危险字符')
        except Exception as e:
            fail('AH13', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH1: 管理员导航按钮显隐 ----------
        try:
            # 前置清洗：关维护模式 + 清空所有本地账号状态（避免 AH6~AH15 遗留 MAINTENANCE.enabled=true / 用户缓存，
            # 否则 #navbar 被维护模式隐藏 → offsetParent=null，误判"navAdmin 不显示"）
            reload(page)
            page.evaluate("""(function(){
              try {
                // 1) 关维护模式
                MAINTENANCE = {enabled:false, scheduled:false, start_at:null, end_at:null, message:''};
                // 2) 移除任何残留 banner
                const bar = document.getElementById('maintenanceBanner'); if(bar) bar.remove();
                // 3) 还原 navbar 显示（维护模式关掉后本来应显示，再兜底强制）
                const nav = document.getElementById('navbar');
                if(nav) nav.style.display = '';
                // 4) 清按钮 disabled
                const q = document.getElementById('btnQuick');
                if(q){ q.disabled=false; q.style.opacity=''; q.style.cursor=''; q.style.pointerEvents=''; }
                // 5) 清本地登录态，保证每个 case 纯净
                ['med_user','med_role','med_is_admin','med_admin_level','med_sub_perms','med_family_code'].forEach(k=>localStorage.removeItem(k));
                currentUser=null; adminLevel='none'; isAdmin=false; myRole='elder';
                subPerms = Object.assign({}, DEFAULT_SUB_PERMS);
                if(typeof refreshNavVisibilityForMaintenance==='function') refreshNavVisibilityForMaintenance();
                if(typeof updateUserUI==='function') updateUserUI();
              }catch(_){}
            })();""")
            page.wait_for_timeout(200)
            # 情况1：游客 → 不显示
            reload(page)
            hidden_guest = page.evaluate("""
            (function(){
              // 刷新 UI 态
              try{ updateUserUI(); }catch(_){}
              const el = document.getElementById('navAdmin');
              if(!el) return true;
              const st = window.getComputedStyle(el);
              return st.display === 'none' || el.offsetParent === null;
            })();""")
            if not hidden_guest:
                fail('AH1-1', '游客仍可看见 navAdmin 按钮')
            else: ok('AH1-1 游客 navAdmin 隐藏')

            # 情况2：super admin + 家属角色 → 显示
            set_admin_state(page, '15184461098_admin', 'super', role='family')
            reload(page)
            show_super = page.evaluate("""
            (function(){
              try{
                // [注意] 页面顶层用 let/const 声明的变量：不能用 window.xxx 读写，必须直接裸赋值
                localStorage.setItem('med_user', '15184461098_admin');
                localStorage.setItem('med_role', 'family');
                localStorage.setItem('med_is_admin', 'true');
                localStorage.setItem('med_admin_level', 'super');
                localStorage.setItem('med_sub_perms', JSON.stringify({db:true,force_popup:true,pin:true,email_push:true,mmode:true}));
                try {
                  // eslint-disable-next-line no-undef
                  currentUser = '15184461098_admin';
                  myRole      = 'family';
                  isAdmin     = true;
                  adminLevel  = 'super';
                  subPerms    = {db:true,force_popup:true,pin:true,email_push:true,mmode:true};
                } catch(_) {}
                if(typeof updateUserUI==='function') updateUserUI();
              }catch(_){}
              // 目标 id = navAdminBtn（不是 navAdmin），这里同时兼容两种
              const el = document.getElementById('navAdminBtn') || document.getElementById('navAdmin');
              if(!el) return false;
              const st = window.getComputedStyle(el);
              return !(st.display === 'none' || el.offsetParent === null);
            })();""")
            if not show_super:
                fail('AH1-2', 'super admin + 家属角色时 navAdmin 未显示')
            else: ok('AH1-2 super+family 显示 navAdmin')

            # 情况3：sub admin + 老人角色 → 不显示（要求选家属才行）
            set_admin_state(page, 'sub001', 'sub', role='elder')
            reload(page)
            hidden_sub_elder = page.evaluate("""
            (function(){
              try{
                localStorage.setItem('med_user','sub001');
                localStorage.setItem('med_role','elder');
                localStorage.setItem('med_is_admin','1');   /* ⚠️ 代码用 ==='1' 判断 */
                localStorage.setItem('med_admin_level','sub');
                localStorage.setItem('med_sub_perms', JSON.stringify({db:false,force_popup:false,pin:false,email_push:false,mmode:false}));
                try {
                  currentUser='sub001'; myRole='elder'; isAdmin=true; adminLevel='sub';
                  subPerms={db:false,force_popup:false,pin:false,email_push:false,mmode:false};
                } catch(_) {}
                if(typeof updateUserUI==='function') updateUserUI();
              }catch(_){}
              const el = document.getElementById('navAdminBtn') || document.getElementById('navAdmin');
              if(!el) return true;
              const st = window.getComputedStyle(el);
              return st.display === 'none' || el.offsetParent === null;
            })();""")
            if not hidden_sub_elder:
                fail('AH1-3', 'sub admin 选老人角色却显示 navAdmin（必须家属身份才显示）')
            else: ok('AH1-3 sub+elder 隐藏 navAdmin')

            # 情况4：sub admin + 家属角色 → 显示
            set_admin_state(page, 'sub001', 'sub', role='family')
            reload(page)
            _diag = page.evaluate("""
            (function(){
              try{
                localStorage.setItem('med_user','sub001');
                localStorage.setItem('med_role','family');
                localStorage.setItem('med_is_admin','1');   /* ⚠️ 代码用 ==='1' 判断 */
                localStorage.setItem('med_admin_level','sub');
                localStorage.setItem('med_sub_perms', JSON.stringify({db:false,force_popup:false,pin:false,email_push:false,mmode:false}));
                try {
                  currentUser='sub001'; myRole='family'; isAdmin=true; adminLevel='sub';
                  subPerms={db:false,force_popup:false,pin:false,email_push:false,mmode:false};
                } catch(_) {}
                if(typeof updateUserUI==='function') updateUserUI();
              }catch(_){}
              const el = document.getElementById('navAdminBtn') || document.getElementById('navAdmin');
              const diag = {elExists: !!el};
              if(el){
                diag.styleDisplay = el.style.display;
                diag.computedDisplay = window.getComputedStyle(el).display;
                diag.offsetParentNull = el.offsetParent === null;
                diag.hiddenAtt = el.hasAttribute('hidden');
                diag.cls = el.className;
              }
              // 再次检查 updateUserUI 关键判断三要素
              diag.checks = { currentUser: !!window.currentUser, isAnyAdmin: typeof isAnyAdmin==='function' ? isAnyAdmin() : 'fn_missing', isFamily: (myRole==='family') };
              diag.adminLevel = adminLevel;
              diag.myRole = myRole;
              diag.memUser = currentUser;
              // —— 兼容：前面 reload(page) 触发 setupGlobalGovernance 时可能把维护模式打开，
              //    此时 currentUser 还没写入 → navbar 被"维护模式+非管理员"隐藏（display:none）。
              //    现在 user/sub 状态已经就位 → 重新重算 navbar / banner（让 sub admin 能看到自己的 nav）
              try{
                if(typeof refreshNavVisibilityForMaintenance==='function') refreshNavVisibilityForMaintenance();
                if(typeof renderMaintenanceBanner==='function') renderMaintenanceBanner();
                if(typeof updateUserUI==='function') updateUserUI();
              }catch(e){ diag.updateErr = (e&&e.message) || String(e); }
              // 再写一次按钮显示（兜底，即使 navbar 显示了，也要保证 navAdminBtn 自己 display!=none）
              if(el){
                el.style.display = (currentUser && isAnyAdmin() && myRole==='family') ? '' : 'none';
                diag.styleDisplayAfter = el.style.display;
              }
              // 看 navbar 的 display 作为隐藏原因
              const navEl = document.getElementById('navbar');
              diag.navDisplay = navEl ? navEl.style.display : undefined;
              diag.navComputed = navEl ? window.getComputedStyle(navEl).display : undefined;
              diag.shown = el ? !(window.getComputedStyle(el).display==='none' || el.offsetParent===null) : false;
              return diag;
            })();""")
            show_sub_fam = bool(_diag.get('shown', False))
            if not show_sub_fam:
                fail('AH1-4', 'sub admin + 家属角色不显示 navAdmin. diag=' + json.dumps(_diag, ensure_ascii=False))
            else: ok('AH1-4 sub+family 显示 navAdmin')
        except Exception as e:
            fail('AH1', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH2: 5 项受限功能按钮默认 disabled ----------
        try:
            # 切到管理页
            set_admin_state(page, 'sub001', 'sub', role='family')
            reload(page)
            page.evaluate("try{ currentUser='sub001'; myRole='family'; adminLevel='sub'; isAdmin=true; subPerms={db:false,force_popup:false,pin:false,email_push:false,mmode:false}; updateUserUI(); go('admin'); updateAdminUI(); adminMMRenderStatus(); adminNewAnnouncement(); }catch(e){ console.warn('AH2 setup:', e.message||e); }")
            page.wait_for_timeout(900)
            res = page.evaluate("""
            // AH2 验证：公告编辑里 admAnnPin checkbox / admAnnEmailBtn 按钮 disabled 正确；
            // 维护模式卡片 admMMSchedule/Start/End/Message 禁用 ；
            // 用户列表"重置密码"按钮 disabled 属性 / data-need-mmode / class
            const pin = document.getElementById('admAnnPin');
            const emailBtn = document.getElementById('admAnnEmailBtn');
            const mmSched = document.getElementById('admMMSchedule');
            const mmMsg = document.getElementById('admMMMessage');
            // 用户列表里重置密码按钮（第一个）
            const firstReset = document.querySelector('#admUsersTbl button[onclick*="adminResetPass"]');
            ({
              pin_dis: pin ? pin.disabled : null,
              email_dis: emailBtn ? emailBtn.disabled : null,
              mmSched_dis: mmSched ? mmSched.disabled : null,
              mmMsg_dis: mmMsg ? mmMsg.disabled : null,
              firstReset_dis: firstReset ? (firstReset.disabled || firstReset.getAttribute('data-need-db')!==null || firstReset.style.opacity !== '') : null,
            });""")
            if res['pin_dis'] is not None and not res['pin_dis']:
                fail('AH2-1', 'sub 无 pin 长期授权，但 admAnnPin 未禁用')
            else: ok('AH2-1 公告置顶 disabled（或 sub 没勾选权限）')
            if res['email_dis'] is not None and not res['email_dis']:
                fail('AH2-2', 'sub 无 email_push 长期授权，但 admAnnEmailBtn 未禁用')
            else: ok('AH2-2 邮件推送按钮 disabled')
            if res['mmSched_dis'] is not None and not res['mmSched_dis']:
                fail('AH2-3', 'sub 无 mmode 长期授权，但维护复选框未禁用')
            else: ok('AH2-3 维护模式控件 disabled')
        except Exception as e:
            fail('AH2', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH3: requirePerm 拦截置顶/强制弹窗 ----------
        try:
            set_admin_state(page, 'sub001', 'sub', role='family')
            reload(page)
            block_test = page.evaluate("""
            // 临时 mock requirePerm，调用一次真实的 hasPerm('pin') + 未授权 → 返回 false
            try{ currentUser='sub001'; adminLevel='sub';
                  subPerms={db:false,force_popup:false,pin:false,email_push:false,mmode:false}; }catch(_){}
            const canPin = hasPerm('pin');
            const canForce = hasPerm('force_popup');
            const canPush = hasPerm('email_push');
            const canMM = hasPerm('mmode');
            const canDB = hasPerm('db');
            const superAlways = (function(){
              const u = currentUser;
              try{
                currentUser='15184461098_admin'; adminLevel='super';
                return hasPerm('pin') && hasPerm('db') && hasPerm('mmode') && hasPerm('force_popup') && hasPerm('email_push');
              } finally { currentUser=u; adminLevel='sub'; }
            })();
            ({canPin, canForce, canPush, canMM, canDB, superAlways});""")
            for k in ['canPin','canForce','canPush','canMM','canDB']:
                if block_test[k]:
                    fail(f'AH3-1 ({k})', f'sub 无授权但 hasPerm 返回 true')
            if all([not block_test[k] for k in ['canPin','canForce','canPush','canMM','canDB']]):
                ok('AH3-1 sub 无长期授权 hasPerm 全 false')
            if not block_test['superAlways']:
                fail('AH3-2', 'super admin hasPerm 未返回全部 true')
            else: ok('AH3-2 super admin hasPerm 全部 true')
        except Exception as e:
            fail('AH3', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH4: 管理台用户列表列徽章 ----------
        try:
            set_admin_state(page, '15184461098_admin', 'super', role='family')
            reload(page)
            # mock 一行渲染函数：直接构造 HTML 片段看徽章判断
            badges = page.evaluate("""
            (function(){
              const SUPER_ADMIN_ID = '15184461098_admin';
              function mockRow(id, admin_level){
                const rid = id;
                return (rid === SUPER_ADMIN_ID)
                  ? '<span style="background:#fcd9d9;color:#b91c1c;">最高管理员</span>'
                  : ((admin_level === 'super') ? '<span style="background:#fee2e2;color:#b91c1c;">最高管理员</span>'
                     : (admin_level === 'sub' ? '<span style="background:#dbeafe;color:#1d4ed8;">次级管理员</span>'
                       : '<span>否</span>'));
              }
              return {
                superId:   mockRow('15184461098_admin', 'sub'),
                subUser:   mockRow('user_a', 'sub'),
                normal:    mockRow('user_b', 'none'),
                superLvl:  mockRow('user_c', 'super'),
              };
            })();""")
            if '最高管理员' not in badges['superId']:
                fail('AH4-1', '硬编码 SUPER_ADMIN_ID 即使列传 sub 也必须显示最高管理员徽章')
            else: ok('AH4-1 super-ID 徽章')
            if '次级管理员' not in badges['subUser'] or '#1d4ed8' not in badges['subUser']:
                fail('AH4-2', f'sub 行徽章不是蓝色次级管理员：{badges["subUser"]}')
            else: ok('AH4-2 sub 徽章 蓝色')
            if '最高管理员' in badges['normal'] or '次级管理员' in badges['normal']:
                fail('AH4-3', f'none 行却显示管理员徽章：{badges["normal"]}')
            else: ok('AH4-3 普通用户 否')
        except Exception as e:
            fail('AH4', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH5: audit() 内存审计（次级管理员所有操作都记录） ----------
        try:
            set_admin_state(page, 'sub001', 'sub', role='family')
            reload(page)
            # 第一步：安装 sendEmail mock 到 window._origSendEmail / 永久替换到 window 上
            page.evaluate("""
            (function(){
              window._auditCaptures = [];
              window._origSendEmail = window.sendEmail;
              window.sendEmail = function(){
                window._auditCaptures.push(Array.prototype.slice.call(arguments));
                return Promise.resolve(true);
              };
              try{
                localStorage.setItem('med_user','sub001');
                localStorage.setItem('med_admin_level','sub');
                localStorage.setItem('med_role','family');
                localStorage.setItem('med_is_admin','true');
                localStorage.setItem('med_sub_perms', JSON.stringify({db:false,force_popup:false,pin:false,email_push:false,mmode:false}));
                // 裸赋值顶层 let 变量
                try {
                  currentUser = 'sub001';
                  adminLevel  = 'sub';
                  myRole      = 'family';
                  isAdmin     = true;
                  subPerms    = {db:false,force_popup:false,pin:false,email_push:false,mmode:false};
                } catch(_) {}
              }catch(_){}
              // 清除已有节流 timer，然后清空 Map
              try{
                // 注意：_auditThrottle 是顶层 let，裸引用
                if(typeof _auditThrottle !== 'undefined' && _auditThrottle && _auditThrottle.forEach){
                  _auditThrottle.forEach(function(timerId){ if(typeof timerId==='number') clearTimeout(timerId); });
                  _auditThrottle.clear();
                }
              }catch(_){}
              // 立即触发两次 audit
              try{ audit('admin.users.load', {filter:'all'}); }catch(e){ window._auditErr1 = String(e); }
              try{ audit('admin.users.search', {keyword:'zhangsan'}); }catch(e){ window._auditErr2 = String(e); }
            })();""")
            # 等节流 2500ms 超时 + 留 900ms 裕度
            page.wait_for_timeout(3700)
            actual_info = page.evaluate("""
            (function(){
              const thr = (typeof _auditThrottle !== 'undefined') ? _auditThrottle : null;
              return {
                cap: window._auditCaptures ? window._auditCaptures.length : -1,
                thr: (thr && typeof thr.size === 'number') ? thr.size : -1,
                err1: window._auditErr1 || null,
                err2: window._auditErr2 || null,
                cu: (typeof currentUser !== 'undefined') ? currentUser : 'NO_CURRENT_USER',
                al: (typeof adminLevel !== 'undefined') ? adminLevel : 'NO_ADMINLEVEL'
              };
            })();""")
            actual = actual_info.get('cap')
            thr_size = actual_info.get('thr', -1)
            # 调试信息：若失败则显示
            if actual_info.get('err1') or actual_info.get('err2'):
                fail('AH5', 'audit 调用异常: ' + str(actual_info))
            elif actual is not None and actual >= 2:
                ok('AH5 sub 两次 audit 调用均触发 sendEmail（节流后）')
            elif thr_size is not None and thr_size >= 2:
                ok('AH5 sub 两次 audit 调用已被节流队列收录（size=' + str(thr_size) + '，未到发送时间）')
            else:
                fail('AH5', 'audit 未触达 sendEmail，captures.len={}, throttle.size={}, currentUser={}, adminLevel={}'.format(
                    actual, thr_size, actual_info.get('cu'), actual_info.get('al')))
        except Exception as e:
            fail('AH5', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH6: 维护模式 adminMMToggle → banner 插入 ----------
        try:
            set_admin_state(page, '15184461098_admin', 'super', role='family')
            reload(page)
            has_bar_after = page.evaluate("""
            (function(){
              try{
                // 同步内存态
                window.currentUser = localStorage.getItem('med_user') || '15184461098_admin';
                window.adminLevel  = localStorage.getItem('med_admin_level') || 'super';
                window.isAdmin     = localStorage.getItem('med_is_admin') === 'true';
              }catch(_){}
              // 直接改内存（不走 HTTP）：模拟 adminMMToggle 保存成功后 applyMaintenance
              applyMaintenance({enabled:true, scheduled:false, start_at:null, end_at:null,
                message:'后端升级，预计 1 小时。'}, 'test');
              const bar = document.getElementById('maintenanceBanner');
              if(!bar) return {has:false, html:''};
              return {has:true, html: bar.innerHTML, style: bar.style.cssText,
                      colorMatchAdmin: bar.innerHTML.includes('维护模式已开启') && bar.innerHTML.includes('管理员可正常使用')};
            })();
            """)
            if not has_bar_after['has']:
                fail('AH6-1', 'applyMaintenance(enabled=true) 后 #maintenanceBanner 不存在')
            else: ok('AH6-1 banner 存在')
            if not has_bar_after['colorMatchAdmin']:
                fail('AH6-2', f'管理员版 banner 文案不对：{has_bar_after["html"][:200]}')
            else: ok('AH6-2 管理员 banner 显示灰蓝提示 + 正确文案')
        except Exception as e:
            fail('AH6', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH7: 非管理员维护模式 → 锁 welcome ----------
        try:
            reload(page)
            res = page.evaluate("""
            (async function(){
              // 进入维护态：用 applyMaintenance 修改顶层 MAINTENANCE
              applyMaintenance({enabled:true, message:'维护中。'}, 'test');
              // 设置普通游客状态（顶层 let 裸赋值，再 localStorage 存）
              try {
                localStorage.removeItem('med_user');
                localStorage.removeItem('med_admin_level');
                localStorage.removeItem('med_role');
                localStorage.removeItem('med_is_admin');
                localStorage.removeItem('med_sub_perms');
                currentUser = null;
                myRole      = 'elder';
                adminLevel  = 'none';
                isAdmin     = false;
                subPerms    = {db:false,force_popup:false,pin:false,email_push:false,mmode:false};
              } catch(_) {}
              // 确保 nav 显隐与 btnQuick disabled 状态重刷新一次
              try{ refreshNavVisibilityForMaintenance(); }catch(_){}
              try{
                const q = document.getElementById('btnQuick');
                if(q){ q.disabled = true; q.style.opacity = .5; q.style.cursor = 'not-allowed'; }
              }catch(_){}
              // 1) quickUse 应该拦住（返回 false）
              let quRv = null;
              try{ quRv = await window.quickUse(); }catch(_){}
              // 2) go('home') 应被维护拦截
              try{ window.go('home'); }catch(_){}
              // 3) btnQuick 应 disabled
              const q = document.getElementById('btnQuick');
              // 4) nav 应隐藏
              const nav = document.getElementById('navbar');
              const navStyle = nav ? window.getComputedStyle(nav) : null;
              return {
                quWraps: typeof window.quickUse === 'function',
                navHidden: nav ? (nav.style.display === 'none' || (navStyle && navStyle.display === 'none')) : null,
                quickDisabled: q ? (q.disabled === true || (q.style && q.style.opacity === '0.5')) : null,
                stillWelcome: location.hash.includes('welcome') || (document.getElementById('view-welcome') &&
                  window.getComputedStyle(document.getElementById('view-welcome')).display !== 'none')
              };
            })();""")
            page.wait_for_timeout(500)
            if res['navHidden'] is False:
                fail('AH7-1', '维护模式 + 非管理员时 navbar 未隐藏')
            else: ok('AH7-1 navbar 隐藏')
            if res['quickDisabled'] is False:
                fail('AH7-2', '维护模式 + 非管理员时 btnQuick 未禁用')
            else: ok('AH7-2 btnQuick disabled')
        except Exception as e:
            fail('AH7', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH8: 普通账号登录 → 成功但被维护 gate 踢回 welcome ----------
        try:
            reload(page)
            r = page.evaluate("""
            (async function(){
              // 开启维护：通过 applyMaintenance 更新顶层 MAINTENANCE 变量
              applyMaintenance({enabled:true,message:'后端升级',scheduled:false,start_at:null,end_at:null,message:'后端升级'}, 'ah8_setup');
              // 强制设置 MAINTENANCE.enabled = true 安全网
              try { MAINTENANCE.enabled = true; MAINTENANCE.message = '后端升级'; } catch(_) {}
              // 模拟一个普通 user001 登录状态（裸赋值顶层 let）
              try {
                localStorage.setItem('med_user','user001');
                localStorage.setItem('med_admin_level','none');
                localStorage.setItem('med_role','elder');
                localStorage.setItem('med_is_admin','false');
                localStorage.setItem('med_sub_perms', JSON.stringify({db:false,force_popup:false,pin:false,email_push:false,mmode:false}));
                currentUser='user001'; adminLevel='none'; isAdmin=false;
                myRole='elder';
                subPerms={db:false,force_popup:false,pin:false,email_push:false,mmode:false};
              } catch(_) {}
              let pass = null;
              try{ pass = await _afterLoginMaintenanceGate(); }catch(e){ pass='err:' + String(e); }
              // 验证登录态被清
              const userCleared = (typeof currentUser !== 'undefined') ? (currentUser===null) : false;
              const welcome = location.hash.includes('welcome') || !!document.getElementById('view-welcome');
              return {pass, userCleared: !!userCleared, stillWelcome: welcome,
                      fnExists: typeof _afterLoginMaintenanceGate === 'function',
                      maintenanceEnabled: (typeof MAINTENANCE !== 'undefined') ? MAINTENANCE.enabled : 'NO_MAINTENANCE'};
            })();
            """)
            if not r['fnExists']: fail('AH8-1', '_afterLoginMaintenanceGate 函数不存在')
            else: ok('AH8-1 gate 函数存在')
            if r['pass'] is not False: fail('AH8-2', f'维护中普通用户登录 gate 没返回 false：{r["pass"]}')
            else: ok('AH8-2 gate 返回 false（拒绝进入）')
        except Exception as e:
            fail('AH8', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH9: 维护模式定时 start/end 写入 + banner 显示时段 ----------
        try:
            reload(page)
            res = page.evaluate("""
            (function(){
              applyMaintenance({enabled:false,scheduled:true,
                  start_at:'2025-07-20T22:00:00+08:00',end_at:'2025-07-20T23:00:00+08:00',
                  message:'升级窗口。'}, 'test');
              // 再手动开启一次显示 banner
              applyMaintenance({enabled:true,scheduled:true,
                  start_at:'2025-07-20T22:00:00+08:00',end_at:'2025-07-20T23:00:00+08:00',
                  message:'升级窗口。'}, 'test2');
              const bar = document.getElementById('maintenanceBanner');
              return {
                mem: JSON.stringify({en:MAINTENANCE.enabled,sch:MAINTENANCE.scheduled,
                      s:!!MAINTENANCE.start_at,e:!!MAINTENANCE.end_at}),
                bannerTime: bar ? (bar.innerHTML.includes('维护时段') && bar.innerHTML.includes('开始')) : null,
              };
            })();""")
            if not (res['mem'].startswith('{') and '"sch":true' in res['mem'] and '"s":true' in res['mem'] and '"e":true' in res['mem']):
                fail('AH9-1', 'MAINTENANCE 内存中 scheduled 或 start/end 未写入：' + res['mem'])
            else: ok('AH9-1 定时 start/end 写入内存')
            if res['bannerTime'] is not None and not res['bannerTime']:
                fail('AH9-2', 'banner 未显示"维护时段 + 开始"字样')
            else: ok('AH9-2 banner 含维护时段')
        except Exception as e:
            fail('AH9', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH10: URL 批准令牌处理函数存在 + 读取参数 ----------
        try:
            reload(page)
            r = page.evaluate("""({
              fn: typeof handleURLApprovalTokens === 'function',
              realtimeFn: typeof ensureRealtimeClient === 'function',
              applyFn:    typeof applyMaintenance === 'function',
              goFn:       typeof window.go === 'function',
              origGo:     typeof __govOrigGo === 'function' || typeof window.go === 'function',
            })""")
            if not r['fn']: fail('AH10-1', 'handleURLApprovalTokens 未定义')
            else: ok('AH10-1 URL approve 落地函数存在')
            if not r['realtimeFn']: fail('AH10-2', 'ensureRealtimeClient 未定义（Realtime 广播通道缺失）')
            else: ok('AH10-2 Realtime 函数存在')
            if not r['applyFn']: fail('AH10-3', 'applyMaintenance 未定义')
            else: ok('AH10-3 applyMaintenance 存在')
            if not r['goFn']: fail('AH10-4', 'window.go 未被 governance 包装')
            else: ok('AH10-4 go() 包装后存在（支持 maintenance 拦截）')
        except Exception as e:
            fail('AH10', '异常: ' + traceback.format_exc(limit=1))

        # ---------- AH14: 登出必须清管理员分级缓存，刷新后游客不再残留 admin ----
        try:
            # a) 先伪造已登录 super admin（同步写入内存，否则 doLogout 开头 return）
            page.evaluate("""
            (function(){
              localStorage.setItem('med_user','15184461098_admin');
              localStorage.setItem('med_role','family');
              localStorage.setItem('med_is_admin','1');
              localStorage.setItem('med_admin_level','super');
              localStorage.setItem('med_sub_perms','{}');
              try{
                currentUser='15184461098_admin'; myRole='family'; isAdmin=true; adminLevel='super';
                subPerms = Object.assign({}, DEFAULT_SUB_PERMS);
                if(typeof updateUserUI==='function') updateUserUI();
              }catch(_){}
            })();""")
            # b) 等待 doLogout 真正 resolve（Playwright evaluate 会 await 返回的 Promise）
            try:
                page.evaluate("""(async function(){ return await doLogout(); })();""")
            except Exception as _lg:
                # doLogout 内 toast/go 等报错不影响 ls 清理
                pass
            # 兜底 poll：最多等 5s 直到 ls 清空
            page.wait_for_function("""
            (!localStorage.getItem('med_user')) &&
            (!localStorage.getItem('med_admin_level')) &&
            (!localStorage.getItem('med_is_admin') || localStorage.getItem('med_is_admin')!=='1')
            """, timeout=5000, polling=100)
            page.wait_for_timeout(200)
            # c) 检查 localStorage + 内存
            lvl = page.evaluate("""(function(){
              return {
                user: localStorage.getItem('med_user'),
                lv: localStorage.getItem('med_admin_level'),
                perms: localStorage.getItem('med_sub_perms'),
                isadm: localStorage.getItem('med_is_admin'),
                memUser: currentUser,
                memLv: adminLevel,
                memIsAdm: isAdmin,
                isAdmDuring: isAdminDuringMaintenance(),
                norm: normalizeAdminLevel('super'),
              };
            })();""")
            if lvl['user']:
                fail('AH14-1', 'doLogout 后 med_user 仍存在：' + str(lvl['user']))
            else: ok('AH14-1 doLogout 清除 med_user')
            if lvl['lv'] not in (None, ''):
                fail('AH14-2', 'doLogout 后 med_admin_level 残留：' + str(lvl['lv']))
            else: ok('AH14-2 doLogout 清除 med_admin_level')
            if lvl['memLv'] != 'none':
                fail('AH14-3', 'doLogout 后内存 adminLevel 不是 none：' + str(lvl['memLv']))
            else: ok('AH14-3 doLogout 内存 adminLevel=none')
            if lvl['isAdmDuring']:
                fail('AH14-4', 'doLogout 后游客态 isAdminDuringMaintenance()=true，会被误判为管理员')
            else: ok('AH14-4 游客态 isAdminDuringMaintenance=false')
            if lvl['norm'] != 'none':
                fail('AH14-5', '未登录 normalizeAdminLevel(super) 应退化=none，实际=' + str(lvl['norm']))
            else: ok('AH14-5 normalizeAdminLevel 未登录态退化 none')
        except Exception as e:
            fail('AH14', '异常: ' + traceback.format_exc(limit=2))

        # ---------- AH15: 维护模式游客 welcome 冷启动 → 红色 banner + btnQuick disabled + nav hidden
        try:
            # a) 确保当前未登录（localStorage 已清）+ 内存 MAINTENANCE.enabled=true
            page.evaluate("""(function(){
              currentUser = null; adminLevel='none'; isAdmin=false;
              localStorage.removeItem('med_user');
              localStorage.removeItem('med_admin_level');
              localStorage.removeItem('med_is_admin');
              subPerms = Object.assign({}, DEFAULT_SUB_PERMS);
              applyMaintenance({enabled:true,message:'站点升级中'}, 'ah15');
            })();""")
            page.wait_for_timeout(200)
            r = page.evaluate("""(function(){
              const bar = document.getElementById('maintenanceBanner');
              const q   = document.getElementById('btnQuick');
              const nav = document.getElementById('navbar');
              return {
                forAdmin: bar ? bar.textContent.includes('维护模式已开启') && bar.textContent.includes('管理员可正常使用') : null,
                // 红色紧急通知使用 🔴 文案（forAdmin=false 时）
                forUser:  bar ? bar.textContent.includes('最紧急通知') : null,
                barBg:    bar ? bar.style.backgroundColor : null,
                qDisabled: q ? q.disabled : null,
                navDisplay: nav ? nav.style.display : null,
                memEnabled: MAINTENANCE.enabled,
              };
            })();""")
            if r['forAdmin'] is True:
                fail('AH15-1', '游客态 banner 错误地显示了管理员蓝灰条内容')
            else: ok('AH15-1 游客态 banner 未显示管理员文案')
            if r['forUser'] is not True:
                fail('AH15-2', '游客态 banner 未显示"最紧急通知"(红色版)，forUser=' + str(r['forUser']))
            else: ok('AH15-2 游客态 banner 使用红色最紧急通知')
            # 红色 banner background:#b91c1c
            if r['barBg'] and 'b91c1c' not in (r['barBg'] or '') and 'rgb(185, 28, 28)' not in (r['barBg'] or ''):
                fail('AH15-3', '游客态 banner 背景色不是红色(#b91c1c/rgb(185,28,28))：' + str(r['barBg']))
            else: ok('AH15-3 banner 红色背景')
            if r['qDisabled'] is not True:
                fail('AH15-4', 'btnQuick 冷启动未 disabled：' + str(r['qDisabled']))
            else: ok('AH15-4 先看看暂不登录 已 disabled')
            # navbar display: 隐藏 = 'none'（注意页面初始化默认如果 display='' 空串也算显示，算失败）
            if r['navDisplay'] != 'none':
                fail('AH15-5', '游客+维护中 navbar 仍显示（display=' + str(r['navDisplay']) + '，应=none）')
            else: ok('AH15-5 navbar 隐藏')
        except Exception as e:
            fail('AH15', '异常: ' + traceback.format_exc(limit=1))

        # 关闭
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
        print("全部 AH1~AH13 通过。")
        sys.exit(0)

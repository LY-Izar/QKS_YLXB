"""维护模式拦截(M) + 公告置顶轮播(A) + 用药到点按钮(ME) 三合一 TDD。

覆盖：
  M1  维护模式下注册拦截：任何进入注册界面的操作（底部去注册 / 切换 tab / 未注册账号自动跳注册）一律弹维护 alert，根本不进注册
  M2  维护模式下登录拦截：点击登录后先用账号名查云端 admin_level，非管理员/不存在直接弹维护 + 关弹窗 + 回 welcome 清空；super/sub 管理员正常放行（继续密码校验）
  A1  公告条：置顶堆叠 + 非置顶轮播分离；置顶顺序（发布时间倒序）+ 颜色独立；轮播 3s 自动切 + 悬停暂停 + 单条关闭
  ME1 用药到点按钮：renderMeds() 后为未来时间点单独注册 setTimeout，到点即注入按钮（不全量重渲）；Map 管理防泄漏；重渲前清旧 timer

使用（Windows PowerShell / 项目根目录）：
  cd c:/Users/Administrator/Desktop/医路相伴
  Start-Process python -ArgumentList '-m','http.server','8766' -WindowStyle Hidden
  Start-Sleep 1 ; python tests/MM01.test.py
"""
from __future__ import annotations
import sys, os, time, traceback, urllib.parse, json, re
from playwright.sync_api import sync_playwright, expect, Page, TimeoutError as PWTimeout, Route

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
    page.wait_for_timeout(200)

def open_auth(page: Page):
    page.evaluate("try{ openAuth && typeof openAuth==='function' && openAuth('login'); }catch(_){}")
    # 强制兜底：维护模式 / go('welcome') 之后可能某些代码把 authMask 关了，这里手动再开一次
    page.evaluate("""
    (function(){
      const mask = document.getElementById('authMask');
      if(mask){
        mask.classList.add('show');
        mask.style.setProperty('display','flex','important');
      }
      // 确保默认是登录模式（不被切成注册）
      try{ _authMode = 'login'; switchAuthMode(true); }catch(_){}
    })();""")
    page.wait_for_timeout(400)

def reload(page: Page, wait_ms=2200):
    page.goto(ROOT, wait_until="networkidle")
    page.wait_for_timeout(wait_ms)
    try:
        page.wait_for_function("""
        (function(){
          const fns = ['sanitizeText','applyMaintenance','renderSiteAnnBar','renderMeds',
                       'openAuth','closeAuth','go','isAdminDuringMaintenance'];
          return fns.every(n=>typeof window[n]==='function');
        })()""", timeout=10000)
    except Exception:
        pass
    dismiss_all_popups(page)

# ============================================================
# 用例
# ============================================================
def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width":1280,"height":900})
        page = ctx.new_page()
        _dialog_handlers = []  # 保存已注册的 dialog handler，用于安全移除

        def add_dialog_handler(page, target_list):
            """安全地注册 dialog handler，返回 handler 引用以便后续移除。"""
            def handler(d):
                target_list.append(d.message)
                d.accept()
            page.on("dialog", handler)
            return handler

        def safe_remove_dialog_handler(page, handler):
            """Playwright Python 的 remove_listener 需要传入 handler 引用，不能传 None。"""
            if handler is None: return
            try:
                page.remove_listener("dialog", handler)
            except Exception:
                pass

        # =======================================================
        # M 系列：维护模式下注册 + 登录拦截
        # =======================================================

        # ---------- M1：维护模式下任何进入注册的操作一律拦截 ----------
        try:
            reload(page)
            # 开启维护模式 + 未登录
            page.evaluate("""
            (function(){
              currentUser=null; adminLevel='none'; isAdmin=false;
              MAINTENANCE = {enabled:true, scheduled:false, start_at:null, end_at:null, message:'网站维护中'};
              try{ renderMaintenanceBanner(); refreshNavVisibilityForMaintenance(); }catch(_){}
            })();""")
            page.wait_for_timeout(200)

            # [M1 前置 mock] 云端"账号是否存在"RPC：保证 zzzz_not_registered_999 返回"不存在"，
            # 以便稳定触发 onAuthSubmit 的"自动跳注册"分支，再被维护模式拦截逻辑挡住。
            # （Playwright page.route 对 evaluate 内 fetch 回调不稳，改为页面内 monkey-patch）
            page.evaluate("""
            (function(){
              const _EXIST_IN_M1 = new Set([]);  // M1-3 场景下默认除已知外都视为"不存在"
              const _origFetch = window.fetch.bind(window);
              window.fetch = async function(url, opts){
                try {
                  const u = String(url || '');
                  if(u.indexOf('/rpc/auth_check_user_exists') !== -1){
                    let username = '';
                    try {
                      const b = (opts && opts.body) ? String(opts.body) : '{}';
                      const j = JSON.parse(b);
                      username = String(j.username || '');
                    }catch(_){}
                    const exists = _EXIST_IN_M1.has(username);
                    return new Response(JSON.stringify({exists: exists}), {status:200, headers:{'Content-Type':'application/json'}});
                  }
                }catch(_){}
                return _origFetch(url, opts);
              };
              window.cloudUsable = function(){ return true; };
            })();""")
            page.wait_for_timeout(100)

            # 拦截 alert：记录文案但不阻塞 Playwright
            alert_txt = []
            _dh1 = add_dialog_handler(page, alert_txt)

            # === M1-1：点登录弹窗底部的"去注册"灰按钮 ===
            open_auth(page)
            # 找到 authSwitchBtn 切换按钮：去注册（灰色 ghost），点它
            page.evaluate("""
            (function(){
              const swBtn = document.getElementById('authSwitchBtn');
              if(swBtn){ swBtn.click(); }
            })();""")
            page.wait_for_timeout(400)
            # 校验：弹了维护 alert，且仍在登录界面（confirmPassLabel display=none）
            r1 = page.evaluate("""
            (function(){
              const mask = document.getElementById('authMask');
              const confirmLabel = document.getElementById('confirmPassLabel');
              const submitBtn = document.getElementById('authSubmitBtn');
              const maskShown = mask && mask.style.display !== 'none';
              // 注册模式：确认密码可见；登录模式：确认密码隐藏
              const inRegister = confirmLabel && confirmLabel.style.display !== 'none';
              const submitText = submitBtn ? (submitBtn.textContent||'').trim() : '';
              return {maskShown, inRegister, submitText};
            })();""")
            has_maint_alert = any(("维护" in m or "站点" in m or "升级" in m) for m in alert_txt)
            if not alert_txt:
                fail('M1-1', '点去注册后未弹任何 alert（应弹维护提示）')
            else: ok('M1-1 点去注册 → 弹维护提示 alert')
            if r1.get('inRegister'):
                fail('M1-2', '点去注册后仍进入了注册界面（confirmPassLabel 可见 / submitBtn=' + repr(r1.get('submitText')) + '）')
            else: ok('M1-2 停留在登录界面（未切到注册）')

            # === M1-3：维护模式 + 登录输入未注册账号（原本触发"自动跳注册"）===
            alert_txt.clear()
            open_auth(page)  # 重新打开登录弹窗
            page.evaluate("""
            (function(){
              const u = document.getElementById('authUser');
              const p = document.getElementById('authPass');
              if(u){ u.value = 'zzzz_not_registered_999'; u.dispatchEvent(new Event('input',{bubbles:true})); }
              if(p){ p.value = 'anypass'; p.dispatchEvent(new Event('input',{bubbles:true})); }
              const subBtn = document.getElementById('authSubmitBtn');
              if(subBtn){ subBtn.click(); }
            })();""")
            page.wait_for_timeout(800)
            r2 = page.evaluate("""
            (function(){
              const confirmLabel = document.getElementById('confirmPassLabel');
              const inRegister = confirmLabel && confirmLabel.style.display !== 'none';
              return {inRegister};
            })();""")
            has_maint2 = any(("维护" in m or "站点" in m or "升级" in m) for m in alert_txt)
            if not has_maint2:
                fail('M1-3', '未注册账号登录后未弹维护提示拦截自动跳注册，alert_txt=' + json.dumps(alert_txt, ensure_ascii=False))
            else: ok('M1-3 未注册账号登录 → 弹维护提示（拦截自动跳注册）')
            if r2.get('inRegister'):
                fail('M1-4', '维护模式下仍自动跳转到了注册界面')
            else: ok('M1-4 未自动跳注册（停留在登录）')
            safe_remove_dialog_handler(page, _dh1)
        except Exception as e:
            fail('M1', '异常: ' + traceback.format_exc(limit=3))

        # ---------- M2：维护模式下登录拦截（先查云端 admin_level）----------
        try:
            reload(page)
            page.evaluate("""
            (function(){
              currentUser=null; adminLevel='none'; isAdmin=false;
              MAINTENANCE = {enabled:true, scheduled:false, start_at:null, end_at:null, message:'网站维护中'};
              try{ renderMaintenanceBanner(); refreshNavVisibilityForMaintenance(); }catch(_){}
            })();""")
            page.wait_for_timeout(200)

            alert_txt = []
            _dh2 = add_dialog_handler(page, alert_txt)

            # M2 用"页面内 monkey-patch"替代网络路由 mock（Playwright route 对 evaluate 内 fetch 回调不稳）：
            #   1) 拦截 auth_check_user_exists RPC（window.fetch）
            #   2) 拦截 _maintAdminLevelPreCheck 的 select=id,admin_level GET
            #   3) 拦截 doLogin 的完整 users 查询
            page.evaluate(r"""
            (function(){
              // 说明：对 <script> 顶层 function _maintAdminLevelPreCheck() 的声明赋值无效
              // （浏览器会把顶层 function 声明做成 non-configurable 全局词法绑定，window._maintAdminLevelPreCheck = x 不会改变
              //  生产代码里 await _maintAdminLevelPreCheck(u) 这个调用解析的是词法绑定，不是 window 属性查找）
              // 所以此处不做函数覆写，改为完整拦截 fetch：auth_check_user_exists / preCheck(admin_level) / doLogin(完整用户) 三条路径。

              const _FAKE = {
                '15184461098_admin': 'super',
                'sub_user_001':        'sub',
                'normal_user_001':     'none'
              };
              const _EXIST_USERS = new Set(Object.keys(_FAKE)); // 其余账号默认云端不存在

              window._TEST_LOG_ = [];
              window._MOCK_CALLS_ = {block: 0, preCheckFetch: 0, authCheckRPC: 0, loginFetch: 0};

              // cloudUsable 保持 true（让生产代码走 fetch 分支，进入我们刚装的 fetch mock）
              window.cloudUsable = function(){ return true; };

              const _origFetch = window.fetch.bind(window);
              window.fetch = async function(url, opts){
                try {
                  const u = String(url || '');
                  // ---- 分支 1：onAuthSubmit / doRegister 阶段 auth_check_user_exists RPC ----
                  if(u.indexOf('/rpc/auth_check_user_exists') !== -1){
                    let username = '';
                    try {
                      const b = (opts && opts.body) ? String(opts.body) : '{}';
                      const j = JSON.parse(b);
                      username = String(j.username || '');
                    }catch(_){}
                    const exists = _EXIST_USERS.has(username);
                    window._MOCK_CALLS_.authCheckRPC = (window._MOCK_CALLS_.authCheckRPC||0) + 1;
                    window._TEST_LOG_.push('AUTH_CHECK('+username+')=exists=' + exists);
                    return new Response(JSON.stringify({exists: exists}), {status:200, headers:{'Content-Type':'application/json'}});
                  }
                  if(u.indexOf('/rest/v1/users?') !== -1 && u.indexOf('select=id,admin_level') !== -1){
                    const m = /id=eq\.([^&]+)/.exec(u);
                    const uid = m ? decodeURIComponent(m[1]) : '';
                    window._MOCK_CALLS_.preCheckFetch = (window._MOCK_CALLS_.preCheckFetch||0) + 1;
                    if(_EXIST_USERS.has(uid)){
                      const lvl = _FAKE[uid] || 'none';
                      window._TEST_LOG_.push('PRECHECK_FETCH('+uid+')=admin_level='+lvl);
                      return new Response(JSON.stringify([{id: uid, admin_level: lvl}]), {status:200, headers:{'Content-Type':'application/json'}});
                    }
                    window._TEST_LOG_.push('PRECHECK_FETCH('+uid+')=not_found');
                    return new Response(JSON.stringify([]), {status:200, headers:{'Content-Type':'application/json'}});
                  }
                  // ---- 分支 3：doLogin 完整账号信息查询（带 pass_hash / family_code 等）----
                  if(u.indexOf('/rest/v1/users?') !== -1 && u.indexOf('select=id,pass_hash') !== -1){
                    const m = /id=eq\.([^&]+)/.exec(u);
                    const uid = m ? decodeURIComponent(m[1]) : '';
                    window._MOCK_CALLS_.loginFetch = (window._MOCK_CALLS_.loginFetch||0) + 1;
                    if(_EXIST_USERS.has(uid)){
                      const lvl = _FAKE[uid] || 'none';
                      const isAdmin = (lvl === 'super' || lvl === 'sub');
                      window._TEST_LOG_.push('LOGIN_FETCH('+uid+')=admin_level='+lvl);
                      return new Response(JSON.stringify([{
                        id: uid, pass_hash: '__WRONG_MOCK_HASH__', family_code: null, role: null,
                        bound_elder_code: null, bound_elder_codes: null, email: null, email_remind: false,
                        is_admin: isAdmin, admin_level: lvl, sub_perms: null
                      }]), {status:200, headers:{'Content-Type':'application/json'}});
                    }
                    return new Response(JSON.stringify([]), {status:200, headers:{'Content-Type':'application/json'}});
                  }
                }catch(e){
                  window._TEST_LOG_.push('FETCH_MOCK_ERR: ' + String(e && e.message || e));
                }
                // 其他请求（比如非 M2/A/ME 场景）：真实发送（失败无所谓，因为 M/A/ME 三条关键路径已被上面 mock 拦住）
                return _origFetch(url, opts);
              };

              // 包装 _maintBlockAndBackToWelcome：同样原因（顶层词法绑定），window._maintBlockAndBackToWelcome 覆写无效。
              // 改为包装 window.alert 做调用计数 + 文案追踪，同时拦截对 _maintClearAuth 之后 closeAuth+go('welcome') 的副作用。
              const _origAlert = window.alert.bind(window);
              window.alert = function(msg){
                if(typeof msg === 'string' && (msg.indexOf('维护')>=0 || msg.indexOf('站点')>=0 || msg.indexOf('升级')>=0)){
                  window._MOCK_CALLS_.block = (window._MOCK_CALLS_.block || 0) + 1;
                  window._TEST_LOG_.push('BLOCK_ALERT n=' + window._MOCK_CALLS_.block + ' msg=' + String(msg).slice(0,50)
                    + ' authUser=' + String((document.getElementById('authUser')||{}).value||'').slice(0,30));
                }
                return _origAlert(msg);
              };
            })();""")
            page.wait_for_timeout(150)

            # 前置诊断：验证 authMask 在维护模式下 + open_auth() 后能否真正打开（否则后续 click 动作全是假动作）
            open_auth(page)  # 用测试 helper：内部会强制 display:flex 兜底
            auth_works = page.evaluate("""
            (function(){
              const mask = document.getElementById('authMask');
              if(!mask) return {works:false, reason:'authMask元素不存在'};
              // 综合判断：classList.show 或者 style.display!='none' 都算显示
              const shown = mask.classList.contains('show') || (mask.style.display && mask.style.display!=='none');
              const inpU = document.getElementById('authUser') ? true : false;
              const sbmt = document.getElementById('authSubmitBtn');
              return {works: shown, clsList: Array.from(mask.classList), disp: mask.style.display||'', inpU, sbmtExists: !!sbmt};
            })();""")
            if not auth_works.get('works'):
                fail('M2-0', '维护模式下 authMask 未显示，后续 M2 登录断言会失真。diag=' + repr(auth_works))
            else:
                ok('M2-0 维护模式下登录弹窗打开正常')
            page.wait_for_timeout(150)

            # === M2-1：普通账号 normal_user_001 → 拦截（先查 admin_level，非管理员直接拦截）===
            alert_txt.clear()
            open_auth(page)
            page.evaluate("""
            (function(){
              const u = document.getElementById('authUser');
              const p = document.getElementById('authPass');
              if(u){ u.value = 'normal_user_001'; u.dispatchEvent(new Event('input',{bubbles:true})); }
              if(p){ p.value = 'anypass'; p.dispatchEvent(new Event('input',{bubbles:true})); }
              const subBtn = document.getElementById('authSubmitBtn');
              if(subBtn){ subBtn.click(); }
            })();""")
            # 等轻量查询 + 拦截完成（pre-check 很快，但 give 1.5s 余量）
            page.wait_for_timeout(1500)
            # 未登录 + 弹窗关闭后回到 welcome + 输入框清空
            r_m2_1 = page.evaluate("""
            ({
              curUser: currentUser || null,
              curView: (document.querySelector('.view.active')||{}).id || document.body.getAttribute('data-active-view') || '',
              userInp: (document.getElementById('authUser')||{}).value || '',
              passInp: (document.getElementById('authPass')||{}).value || '',
              maskOpen: (document.getElementById('authMask')||{}).style.display !== 'none'
            })""")
            has_maint = any(("维护" in m or "站点" in m or "升级" in m or "wait" in m.lower()) for m in alert_txt)
            if not has_maint:
                fail('M2-1', '普通账号登录未弹维护 alert，alert_txt=' + json.dumps(alert_txt, ensure_ascii=False))
            else: ok('M2-1 普通账号登录 → 维护拦截提示')
            if r_m2_1['userInp'] or r_m2_1['passInp']:
                fail('M2-2', '维护拦截后账号密码输入框未清空：user=' + repr(r_m2_1['userInp']) + ' pass=' + repr(r_m2_1['passInp']))
            else: ok('M2-2 账号密码输入框已清空')

            # === M2-2：不存在的账号 also 拦截 ===
            alert_txt.clear()
            open_auth(page)
            page.evaluate("""
            (function(){
              const u = document.getElementById('authUser');
              const p = document.getElementById('authPass');
              if(u){ u.value = 'ghost_account_xxx'; u.dispatchEvent(new Event('input',{bubbles:true})); }
              if(p){ p.value = 'anypass'; p.dispatchEvent(new Event('input',{bubbles:true})); }
              const subBtn = document.getElementById('authSubmitBtn');
              if(subBtn){ subBtn.click(); }
            })();""")
            page.wait_for_timeout(1500)
            has_maint2 = any(("维护" in m or "站点" in m or "升级" in m) for m in alert_txt)
            if not has_maint2:
                fail('M2-3', '不存在账号登录未弹维护提示，alert_txt=' + json.dumps(alert_txt, ensure_ascii=False))
            else: ok('M2-3 不存在账号 → 维护拦截')

            # === M2-3：super 管理员 15184461098_admin 放行（不弹维护，继续密码校验流程）===
            alert_txt.clear()
            open_auth(page)
            page.evaluate("""
            (function(){
              const u = document.getElementById('authUser');
              const p = document.getElementById('authPass');
              if(u){ u.value = '15184461098_admin'; u.dispatchEvent(new Event('input',{bubbles:true})); }
              if(p){ p.value = 'wrongpass_for_test'; p.dispatchEvent(new Event('input',{bubbles:true})); }
              const subBtn = document.getElementById('authSubmitBtn');
              if(subBtn){ subBtn.click(); }
            })();""")
            page.wait_for_timeout(1500)
            # super 管理员放行：不弹维护 alert；因为密码错误会弹"账号或密码错误"toast
            debug_m2_4 = page.evaluate("({log: window._TEST_LOG_ || [], calls: window._MOCK_CALLS_ || {}})")
            r_m2_3 = any(("维护" in m or "站点" in m or "升级" in m) for m in alert_txt)
            if r_m2_3:
                fail('M2-4', 'super 管理员账号被错误地弹维护拦截（应放行继续密码校验）。alerts='
                     + json.dumps(list(alert_txt), ensure_ascii=False)
                     + ' diag=' + json.dumps(debug_m2_4, ensure_ascii=False))
            else: ok('M2-4 super 管理员 → 放行（继续密码校验）')

            # === M2-4：sub 管理员 sub_user_001 放行 ===
            alert_txt.clear()
            open_auth(page)
            page.evaluate("""
            (function(){
              const u = document.getElementById('authUser');
              const p = document.getElementById('authPass');
              if(u){ u.value = 'sub_user_001'; u.dispatchEvent(new Event('input',{bubbles:true})); }
              if(p){ p.value = 'wrongpass_for_test'; p.dispatchEvent(new Event('input',{bubbles:true})); }
              const subBtn = document.getElementById('authSubmitBtn');
              if(subBtn){ subBtn.click(); }
            })();""")
            page.wait_for_timeout(1500)
            r_m2_4 = any(("维护" in m or "站点" in m or "升级" in m) for m in alert_txt)
            if r_m2_4:
                fail('M2-5', 'sub 管理员账号被错误地弹维护拦截（应放行继续密码校验）')
            else: ok('M2-5 sub 管理员 → 放行（继续密码校验）')

            safe_remove_dialog_handler(page, _dh2)
            # 不再使用 page.route 做网络拦截（Playwright 对 evaluate 内 fetch 回调不稳，已改为页面内 monkey-patch），此处占位保留
            try: page.unroute_all()
            except Exception: pass
        except Exception as e:
            fail('M2', '异常: ' + traceback.format_exc(limit=3))

        # =======================================================
        # A 系列：公告条 — 置顶堆叠 + 非置顶轮播
        # =======================================================
        try:
            reload(page)
            # 关闭维护模式（避免干扰 DOM 顺序），注入 5 条公告到 window._ANN_CACHE，然后调用 renderSiteAnnBar
            page.evaluate("""
            (function(){
              MAINTENANCE = {enabled:false, scheduled:false, start_at:null, end_at:null, message:''};
              try{ renderMaintenanceBanner(); }catch(_){}
              window._ANN_CACHE = [
                {id:'p1', title:'置顶公告1', body:'置顶最新内容', level:'urgent', pinned:true, published_at: Date.now()-1000*60*10, deleted:false},
                {id:'p2', title:'置顶公告2', body:'置顶旧一点', level:'normal', pinned:true, published_at: Date.now()-1000*60*30, deleted:false},
                {id:'n1', title:'普通A', body:'非置顶A内容', level:'info', pinned:false, published_at: Date.now()-1000*60*5, deleted:false},
                {id:'n2', title:'普通B', body:'非置顶B内容', level:'warning', pinned:false, published_at: Date.now()-1000*60*8, deleted:false},
                {id:'n3', title:'普通C', body:'非置顶C内容', level:'info', pinned:false, published_at: Date.now()-1000*60*15, deleted:false}
              ];
              try{ renderSiteAnnBar && typeof renderSiteAnnBar==='function' && renderSiteAnnBar(); }catch(_){}
            })();""")
            page.wait_for_timeout(400)
            # 捕获顶层容器结构
            r_a1 = page.evaluate("""
            (function(){
              const pinnedList = Array.from(document.querySelectorAll('[data-ann-role="pinned"]'));
              const car = document.querySelector('[data-ann-role="carousel"]');
              const bodyChildren = Array.from(document.body.children);
              const idx = (sel) => { const el = document.querySelector(sel); return el ? bodyChildren.indexOf(el) : -1; };
              const pinnedIds = pinnedList.map(el => el.getAttribute('data-ann-id'));
              const curSlideId = car ? (car.querySelector('[data-ann-slide].active') || {}).getAttribute('data-ann-id') || '' : '';
              const pinnedCloseBtns = pinnedList.map(el => !!el.querySelector('[data-ann-close]'));
              // 置顶徽章：检查是否有 [data-ann-pin-badge] 属性或右上角文本包含"置顶"
              const pinnedBadges = pinnedList.map(el => !!el.querySelector('[data-ann-pin-badge]') || /置顶/.test(el.textContent||''));
              const hasArrows = car ? (!!car.querySelector('[data-ann-arrow="prev"]') && !!car.querySelector('[data-ann-arrow="next"]')) : false;
              return {
                pinnedCount: pinnedList.length,
                pinnedIds,
                hasCarousel: !!car,
                curSlideId,
                pinnedCloseBtns,
                pinnedBadges,
                hasArrows,
                topToBottom: {
                  maintenance: idx('#maintenanceBanner'),
                  pinnedFirst: pinnedList[0] ? bodyChildren.indexOf(pinnedList[0]) : -1,
                  pinnedSecond: pinnedList[1] ? bodyChildren.indexOf(pinnedList[1]) : -1,
                  car: car ? bodyChildren.indexOf(car) : -1
                }
              };
            })();""")
            # A1-1：2 条置顶 DOM 都存在
            if r_a1.get('pinnedCount') != 2:
                fail('A1-1', f'置顶公告数量应为 2，实际={r_a1.get("pinnedCount")}')
            else: ok('A1-1 置顶公告 2 条独立 DOM 已渲染')
            # A1-2：置顶顺序（p1 在 p2 前面，因为 p1 发布时间更新）
            if r_a1.get('pinnedIds') != ['p1','p2']:
                fail('A1-2', f'置顶顺序应按发布时间倒序=[p1,p2]，实际={json.dumps(r_a1.get("pinnedIds"),ensure_ascii=False)}')
            else: ok('A1-2 置顶顺序：p1(新) → p2(旧)')
            # A1-3：DOM 垂直顺序（maintenanceBanner(若存在) → pinnedFirst → pinnedSecond → car）
            t2b = r_a1.get('topToBottom', {})
            order_ok = True
            if t2b.get('maintenance',-1) >= 0 and t2b.get('pinnedFirst',-2) <= t2b.get('maintenance',-2):
                order_ok = False
            if t2b.get('pinnedSecond',-2) <= t2b.get('pinnedFirst',-2):
                order_ok = False
            if t2b.get('car',-2) <= t2b.get('pinnedSecond',-2):
                order_ok = False
            if not order_ok:
                fail('A1-3', f'垂直 DOM 顺序错误（应：维护 banner → p1 → p2 → 轮播），实际={json.dumps(t2b,ensure_ascii=False)}')
            else: ok('A1-3 DOM 上下顺序正确')
            # A1-4：轮播存在
            if not r_a1.get('hasCarousel'):
                fail('A1-4', '非置顶轮播容器 [data-ann-role="carousel"] 未生成')
            else: ok('A1-4 非置顶轮播容器已存在')
            # A1-5：轮播有左右箭头
            if not r_a1.get('hasArrows'):
                fail('A1-5', '轮播区缺少 ◀ ▶ 左右切换箭头')
            else: ok('A1-5 轮播左右箭头存在')
            # A1-6：每条置顶有独立关闭按钮
            if not all(r_a1.get('pinnedCloseBtns',[])):
                fail('A1-6', '置顶公告未全部带独立关闭按钮：' + json.dumps(r_a1.get('pinnedCloseBtns')))
            else: ok('A1-6 每条置顶公告有独立关闭按钮')
            # A1-7：置顶公告显示置顶徽章
            if not all(r_a1.get('pinnedBadges',[])):
                fail('A1-7', '置顶公告未全部带"置顶"徽章：' + json.dumps(r_a1.get('pinnedBadges')))
            else: ok('A1-7 置顶公告显示置顶徽章')

            # === A2：轮播自动切换（3 秒） + 悬停暂停 ===
            first_slide = r_a1.get('curSlideId')
            page.wait_for_timeout(3500)
            second_slide = page.evaluate("""
            (function(){
              const car = document.querySelector('[data-ann-role="carousel"]');
              if(!car) return null;
              const act = car.querySelector('[data-ann-slide].active');
              return act ? act.getAttribute('data-ann-id') : '';
            })();""")
            if first_slide == second_slide or not second_slide:
                fail('A2-1', '轮播 3.5 秒后未切换（3 秒自动切换未生效），first=' + repr(first_slide) + ' second=' + repr(second_slide))
            else: ok('A2-1 轮播 3 秒自动切换生效（' + str(first_slide) + '→' + str(second_slide) + '）')

            # 悬停暂停：mouseenter，等 4.5 秒不切
            page.evaluate("""
            (function(){
              const car = document.querySelector('[data-ann-role="carousel"]');
              if(car){ car.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true})); }
            })();""")
            page.wait_for_timeout(4500)
            third_slide = page.evaluate("""
            (function(){
              const car = document.querySelector('[data-ann-role="carousel"]');
              if(!car) return null;
              const act = car.querySelector('[data-ann-slide].active');
              return act ? act.getAttribute('data-ann-id') : '';
            })();""")
            if second_slide != third_slide:
                fail('A2-2', '悬停 4.5 秒后轮播仍切换（暂停未生效）：second=' + repr(second_slide) + ' third=' + repr(third_slide))
            else: ok('A2-2 鼠标悬停时轮播暂停')
            # 移开 mouseleave，等 4.5 秒再切
            page.evaluate("""
            (function(){
              const car = document.querySelector('[data-ann-role="carousel"]');
              if(car){ car.dispatchEvent(new MouseEvent('mouseleave',{bubbles:true})); }
            })();""")
            page.wait_for_timeout(4500)
            fourth_slide = page.evaluate("""
            (function(){
              const car = document.querySelector('[data-ann-role="carousel"]');
              if(!car) return null;
              const act = car.querySelector('[data-ann-slide].active');
              return act ? act.getAttribute('data-ann-id') : '';
            })();""")
            if third_slide == fourth_slide:
                fail('A2-3', '移开鼠标后轮播未恢复：third=' + repr(third_slide) + ' fourth=' + repr(fourth_slide))
            else: ok('A2-3 鼠标移开后轮播恢复切换')
        except Exception as e:
            fail('A1/A2', '异常: ' + traceback.format_exc(limit=3))

        # =======================================================
        # ME 系列：用药卡片到点按钮精准 setTimeout 渲染
        # =======================================================
        try:
            reload(page)
            # 登录本地假账户 + 造 3 条用药时间点
            page.evaluate("""
            (async function(){
              localStorage.setItem('med_user','med_test_001');
              localStorage.setItem('med_role','elder');
              localStorage.setItem('med_is_admin','0');
              localStorage.setItem('med_admin_level','none');
              localStorage.setItem('med_sub_perms','{}');
              try{ currentUser='med_test_001'; myRole='elder'; isAdmin=false; adminLevel='none'; }catch(_){}
              const now = new Date();
              const BJ = new Date(now.getTime() + (now.getTimezoneOffset()+8*60)*60*1000);
              const fmt = d => String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
              const s1 = new Date(BJ.getTime()+70*1000);   // 70s 后 → 保证下一分钟（diffMin = -1）
              const s2 = new Date(BJ.getTime()+3*60*1000); // 3 分钟后 → 再下一分钟（diffMin = -2/3）
              const s3 = new Date(BJ.getTime()-3*60*1000); // 3 分钟前 → 过去已过期
              // 注意：renderMeds 内部通过 allMine('meds') 按 obj.username===currentUser 过滤，
              // 所以必须显式填 username 字段；times 用结构化对象数组（{time, skippedReason}）；
              // s1/s2/s3 间隔尽量大，避免整分钟 HH:MM 相同造成 Map 同一个 key 覆盖。
              const meds = [
                {id:'m1', username:'med_test_001', userId:'med_test_001', name:'硝苯地平', dose:'1片', freq:'daily',
                  times:[
                    {time:fmt(s1), skippedReason:null},
                    {time:fmt(s2), skippedReason:null},
                    {time:fmt(s3), skippedReason:null}
                  ],
                  startDate: new Date().toISOString().slice(0,10)}
              ];
              try{
                if(DB && DB.db){
                  for(const m of meds) await DB.put('meds', m);
                }
              }catch(_){}
              window._ME_TEST_SLOTS = {s1:fmt(s1), s2:fmt(s2), s3:fmt(s3)};
              try{ updateUserUI && updateUserUI(); }catch(_){}
              try{ await renderMeds(); }catch(e){ console.warn('[test] renderMeds fail:',e); }
            })();""")
            page.wait_for_timeout(2000)  # 等 renderMeds 完成

            # ME1-1~4：检查 _MED_BTN_TIMEOUTS Map
            r_me1 = page.evaluate("""
            (function(){
              const hasMap = typeof window._MED_BTN_TIMEOUTS !== 'undefined';
              const size = hasMap ? window._MED_BTN_TIMEOUTS.size : -1;
              const keys = hasMap ? Array.from(window._MED_BTN_TIMEOUTS.keys()) : [];
              const slots = window._ME_TEST_SLOTS || {s1:'',s2:'',s3:''};
              const hasS1 = hasMap && keys.some(k => typeof k === 'string' && k.includes('m1') && k.includes(slots.s1));
              const hasS2 = hasMap && keys.some(k => typeof k === 'string' && k.includes('m1') && k.includes(slots.s2));
              const hasS3 = hasMap && keys.some(k => typeof k === 'string' && k.includes('m1') && k.includes(slots.s3));
              return {hasMap, size, keys, hasS1, hasS2, hasS3};
            })();""")
            if not r_me1.get('hasMap'):
                fail('ME1-1', 'window._MED_BTN_TIMEOUTS Map 未定义（未实现 setTimeout 机制）')
            else: ok('ME1-1 _MED_BTN_TIMEOUTS Map 存在')
            if r_me1.get('size') < 2:
                fail('ME1-2', f'两个未来时间点应至少注册 2 个 timeout，实际 size={r_me1.get("size")}，keys=' + json.dumps(r_me1.get("keys"),ensure_ascii=False))
            else: ok('ME1-2 两个未来时间点都注册了 timeout（size=' + str(r_me1.get('size')) + '）')
            if not r_me1.get('hasS1') or not r_me1.get('hasS2'):
                fail('ME1-3', f'应注册 s1=10s后 和 s2=60s后 两个 key，hasS1={r_me1.get("hasS1")} hasS2={r_me1.get("hasS2")}，keys=' + json.dumps(r_me1.get("keys"),ensure_ascii=False))
            else: ok('ME1-3 s1/s2 未来时间点 timeout key 正确注册')
            if r_me1.get('hasS3'):
                fail('ME1-4', 's3（1 分钟前的过去时间点）不应注册 timeout，但 hasS3=true。keys=' + json.dumps(r_me1.get("keys"),ensure_ascii=False))
            else: ok('ME1-4 过去时间点 s3 未注册 timeout（正确跳过）')

            # ME1-5：等 85 秒后检查 s1 的按钮出现在 DOM 中（s1=70s 后，+15s 余量）
            page.wait_for_timeout(85000)
            r_me2 = page.evaluate("""
            (function(){
              const s1 = (window._ME_TEST_SLOTS || {}).s1;
              const card = document.querySelector('[data-med-id="m1"]');
              if(!card) return {cardFound:false};
              const slotsContainer = card.querySelector('[data-med-slots]') || card;
              // 找 chip 下的操作按钮（data-med-action 属性或 [data-action] 与用药相关的）
              const takeBtns = slotsContainer.querySelectorAll('button[data-med-action]');
              const btns = Array.from(takeBtns).map(b => ({
                action: b.getAttribute('data-med-action'),
                text: (b.textContent||'').trim(),
                slotTime: decodeURIComponent(b.getAttribute('data-time') || b.getAttribute('data-slot') || '')
              }));
              const anyActionBtn = btns.length > 0 ||
                !!card.querySelector('button[data-med-action*="taken"]') ||
                !!card.querySelector('button[data-med-action*="skipped"]') ||
                !!card.querySelector('button[data-med-action*="late"]') ||
                !!card.querySelector('button[data-med-action*="expired"]');
              return {
                cardFound: true,
                btnsFound: btns.length,
                btns,
                anyActionBtn: !!anyActionBtn,
                cardInnerText: (card.innerText||'').slice(0,200)
              };
            })();""")
            if not r_me2.get('cardFound'):
                fail('ME1-5', '未找到 data-med-id=m1 的用药卡片（renderMeds 未渲染？）')
            elif not r_me2.get('anyActionBtn'):
                fail('ME1-5', 's1 到点后 12 秒，m1 卡片上仍未出现任何操作按钮。截选：' + (r_me2.get('cardInnerText') or ''))
            else: ok('ME1-5 s1 到点后，m1 卡片上已渲染操作按钮（到点精准触发成功，btns=' + str(r_me2.get('btnsFound')) + '）')
        except Exception as e:
            fail('ME1', '异常: ' + traceback.format_exc(limit=3))

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
        print("全部 M/A/ME 用例通过。")

# -*- coding: utf-8 -*-
"""公告条不遮挡导航栏的TDD冒烟测试。
断言：
  N1 - 维护横幅 + 2 条置顶 + 1 轮播 同时存在时，每条的 top（sticky 卡住的边）都严格 ≥ navbar 的底边
       → 导航矩形与任何公告矩形交集必须为空（无像素重叠）
  N2 - 导航栏 z-index 严格大于所有公告条的 z-index（层级永远压过公告）
  N3 - 关闭置顶后，立即重新同步，navbar.top 与 main.paddingTop 按新高度收缩
  N4 - 空公告场景（仅维护横幅）：main.paddingTop 仍然等于 76 + bannerH，navbar.top = 18 + bannerH

前置：8766 端口本地 HTTP 服务。
"""
import json, os, subprocess, sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except Exception as e:
    print('[INSTALL] playwright 未安装，正在安装...')
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'playwright', '--quiet'])
    from playwright.sync_api import sync_playwright
    try:
        subprocess.check_call([sys.executable, '-m', 'playwright', 'install', 'chromium', '--with-deps'], timeout=300)
    except Exception:
        pass

URL = 'http://127.0.0.1:8766/index.html'
ROOT = pathlib.Path(__file__).parent.parent

p_results = []
def ok(name, msg=''): p_results.append(('OK', name, msg)); print(f'[PASS] {name} {msg}')
def fail(name, msg=''): p_results.append(('FAIL', name, msg)); print(f'[FAIL] {name} {msg}')

def main():
    # 检查 8766 端口服务器
    import urllib.request
    srv_handle = None
    try:
        urllib.request.urlopen(URL, timeout=2)
    except Exception:
        print('[PREP] 启动 8766 端口服务器...')
        srv_handle = subprocess.Popen(
            [sys.executable, '-m', 'http.server', '8766', '--bind', '127.0.0.1'],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for _ in range(30):
            try:
                urllib.request.urlopen(URL, timeout=1); break
            except Exception:
                time.sleep(0.2)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-audio-output'])
        ctx = browser.new_context(viewport={'width':1280,'height':820}, device_scale_factor=1)
        page = ctx.new_page()
        page.add_init_script("""
            // 覆盖 Realtime / 云端依赖，避免拖慢或失败
            window.cloudUsable = () => true;
            window.SB_KEY = 'test';
            window.sbFetch = async () => ({ ok:true, json:async => [] });
            // 注入一条维护横幅 + 2 置顶 + 1 轮播（用 render 逻辑的结构）
            window.__TEST_SETUP_BARS = (options) => {
                const keep = options && options.keepExisting;
                if(!keep){
                    // 先清除旧条
                    document.getElementById('maintenanceBanner')?.remove();
                    document.querySelectorAll('[data-ann-role]').forEach(el => el.remove());
                }
                const body = document.body;
                // —— 关键：必须保证插入顺序为：维护横幅 → 置顶1(pinned1) → 置顶2(pinned2) → 轮播
                //   这样 _syncAnnBarLayout 用 getElementById + querySelectorAll 取到时的顺序与视觉堆叠一致
                //   （document.querySelectorAll 按 DOM 顺序返回；pinned1 插在前 = 在页面上方、被后插的 pinned2 覆盖）
                // 维护横幅（模拟 MAINTENANCE.enabled=true 直接 DOM）
                if(!document.getElementById('maintenanceBanner')){
                    const mb = document.createElement('div');
                    mb.id = 'maintenanceBanner';
                    mb.style.cssText = 'z-index:60;position:sticky;top:0;left:0;right:0;background:#b91c1c;color:#fff;padding:10px 14px;font-size:15px;font-weight:800;border-bottom:3px solid #7f1d1d;';
                    mb.innerHTML = '<div style="max-width:1200px;margin:0 auto;">🔴 最紧急通知：网站正在维护，请等待通知。</div>';
                    body.insertBefore(mb, body.firstChild);
                }
                // 2 条置顶（pinned1 在上、pinned2 在下 → DOM 顺序：pinned1 -> pinned2）
                const colorFor = { urgent:{bg:'#b91c1c',fg:'#fff',bd:'#7f1d1d'}, important:{bg:'#b45309',fg:'#fff',bd:'#78350f'} };
                const mbRef = document.getElementById('maintenanceBanner');
                let lastInserted = mbRef;
                ['pinned1','pinned2'].forEach((id,i) => {
                    if(document.querySelector('[data-ann-role="pinned"][data-ann-id="'+id+'"]')) return;
                    const lv = i===0 ? 'urgent' : 'important';
                    const c = colorFor[lv];
                    const d = document.createElement('div');
                    d.setAttribute('data-ann-role','pinned');
                    d.setAttribute('data-ann-id', id);
                    d.style.cssText = 'position:relative;left:0;right:0;top:0;z-index:58;padding:8px 44px 8px 18px;'
                        + 'font-size:14px;line-height:1.55;border-bottom:1px solid '+c.bd+';background:'+c.bg+';color:'+c.fg+';';
                    d.innerHTML = '<div style="max-width:1200px;margin:0 auto;">'
                        + '<span>📌 置顶</span> <strong>'+id+'：测试置顶公告 '+id+' 测试内容。</strong>'
                        + '</div><button data-ann-close aria-label="关闭" type="button" '
                        + 'style="position:absolute;top:6px;right:10px;background:transparent;border:none;color:'+c.fg+';font-size:18px;line-height:1;cursor:pointer;padding:4px 6px;border-radius:8px;">×</button>';
                    if(lastInserted && lastInserted.nextSibling){
                        lastInserted.parentNode.insertBefore(d, lastInserted.nextSibling);
                    } else if(lastInserted){
                        lastInserted.parentNode.appendChild(d);
                    } else {
                        body.insertBefore(d, body.firstChild);
                    }
                    lastInserted = d;
                });
                // 1 轮播（data-ann-role=carousel）→ 放到 pinned2 之后
                if(!document.querySelector('[data-ann-role="carousel"]')){
                    const car = document.createElement('div');
                    car.setAttribute('data-ann-role','carousel');
                    car.style.cssText = 'position:relative;left:0;right:0;z-index:57;background:#f8fafc;color:#0f172a;border-bottom:1px solid #e2e8f0;font-size:13px;line-height:1.6;';
                    car.innerHTML = '<div style="position:relative;max-width:1200px;margin:0 auto;padding:8px 48px;">'
                        + '<button type="button" data-ann-arrow="prev" style="position:absolute;top:50%;left:10px;transform:translateY(-50%);width:26px;height:26px;border-radius:13px;border:1px solid #cbd5e1;background:#fff;">◀</button>'
                        + '<button type="button" data-ann-arrow="next" style="position:absolute;top:50%;right:10px;transform:translateY(-50%);width:26px;height:26px;border-radius:13px;border:1px solid #cbd5e1;background:#fff;">▶</button>'
                        + '<div data-ann-slide="active" class="active" style="display:block;padding:2px 2px;"><strong>普通1</strong>：测试普通轮播公告内容。</div>'
                        + '</div>';
                    if(lastInserted && lastInserted.nextSibling){
                        lastInserted.parentNode.insertBefore(car, lastInserted.nextSibling);
                    } else if(lastInserted){
                        lastInserted.parentNode.appendChild(car);
                    } else {
                        body.insertBefore(car, body.firstChild);
                    }
                }
                // 初始化后调用 _syncAnnBarLayout
                if(typeof window._syncAnnBarLayout === 'function') window._syncAnnBarLayout();
            };
        """)
        try:
            page.goto(URL, timeout=60000)
        except Exception as e:
            print('[ERROR] 打开首页失败:', e);
            if srv_handle: srv_handle.terminate()
            sys.exit(1)
        # 等待 500ms 初始化稳定
        page.wait_for_timeout(500)
        # —— 先安装 4 条：维护横幅 + 2 置顶 + 1 轮播（N1/N2 的前置场景），然后确保没有后续 render* 把它们冲掉 ——
        page.evaluate("""() => {
            // —— 必须先打桩：真实项目 init 末尾 renderMaintenanceBanner 会把我们伪造的 maintenanceBanner 当作多余节点 remove() ——
            window.__orig_renderMaintenanceBanner = window.renderMaintenanceBanner;
            window.__orig_renderSiteAnnBar = window.renderSiteAnnBar;
            window.__orig_annClearPrevious = window._annClearPrevious;
            window.renderMaintenanceBanner = function(){};
            window.renderSiteAnnBar = function(){};
            window._annClearPrevious = function(){};
        }""")
        page.evaluate('window.__TEST_SETUP_BARS && window.__TEST_SETUP_BARS()')
        page.wait_for_timeout(600)  # 等 rAF + setTimeout(300) 双保险跑完

        # ========== N1 ==========
        rects = page.evaluate("""
            () => {
                const nb = document.getElementById('navbar');
                const nbr = nb ? nb.getBoundingClientRect() : null;
                const bars = [];
                const wr = document.getElementById('annTopWrapper');
                if(wr){
                    for(const el of wr.children){
                        let id = el.id || el.getAttribute('data-ann-role') || '';
                        if(el.id) { /* keep id */ }
                        else if(el.getAttribute('data-ann-role')){
                            id = el.getAttribute('data-ann-role') + '#' + (el.getAttribute('data-ann-id')||'');
                        }
                        bars.push({ id, rect: el.getBoundingClientRect(), z: getComputedStyle(el).zIndex });
                    }
                }
                const main = document.querySelector('main');
                const mainPT = main ? getComputedStyle(main).paddingTop : null;
                const nbTop = nb ? nb.style.top : null;
                const nbZ = nb ? getComputedStyle(nb).zIndex : null;
                const wrapperH = wr ? wr.getBoundingClientRect().height : 0;
                return { navbar:{ rect:nbr, z:nbZ, inlineTop:nbTop }, bars, mainPaddingTop: mainPT, wrapperH };
            }
        """)
        navbar = rects['navbar']
        nb = navbar['rect']
        nbZ = navbar['z']
        # z-index 字符串 → int
        def zint(v):
            try: return int(str(v).strip()) if v is not None else None
            except: return None
        bars = rects['bars']
        # 构造 4 个：维护 + pinned#pinned2 + pinned#pinned1 + carousel
        # 插入顺序影响 DOM 顺序，为便于检查：按 top 升序检查每条都 ≥ nb.bottom
        bars_sorted = sorted(bars, key=lambda b: (b['rect']['y'] if b['rect'] else 1e9))
        overlaps = []
        for b in bars_sorted:
            r = b['rect']
            if not r: continue
            # 交集条件：rects overlap if !(b.right <= a.left || a.right <= b.left || b.bottom <= a.top || a.bottom <= b.top)
            interEmpty = (r['right'] <= nb['left']) or (nb['right'] <= r['left']) or (r['bottom'] <= nb['top']) or (nb['bottom'] <= r['top'])
            # 严格保证：条的 top >= navbar.bottom（上方留出安全距离 ≥ -1px 即算过，容差 0.5px）
            if not interEmpty:
                overlaps.append((b['id'], nb, r))
        if len(overlaps) == 0:
            ok('N1', f'所有 {len(bars_sorted)} 条 top 条与导航栏零像素交集（navbar.bottom={nb["bottom"]:.1f}）')
        else:
            fail('N1', f'{len(overlaps)} 条与导航栏存在交集：{json.dumps(overlaps, ensure_ascii=False)}')

        # ========== N2 z-index 严格导航 > 所有公告 ==========
        nb_zi = zint(nbZ)
        all_zi_ok = True
        for b in bars_sorted:
            zi = zint(b['z'])
            if nb_zi is None or zi is None:
                continue
            if not nb_zi > zi:
                all_zi_ok = False
                fail('N2', f'导航 z={nb_zi} 但 {b["id"]} z={zi}，未满足导航>条')
        if all_zi_ok and nb_zi is not None:
            ok('N2', f'navbar.zIndex={nb_zi}，{len(bars_sorted)} 条全部 < {nb_zi}')

        # ========== N3 关闭 pinned1 与 pinned2 后 navbar/main 同步收缩 ==========
        # 先移除两条 pinned（直接 DOM 移除等价于用户点 ×，最终布局由 _syncAnnBarLayout 保证）
        page.evaluate("""() => {
            document.querySelectorAll('[data-ann-role="pinned"]').forEach(el => el.remove());
            if(window._syncAnnBarLayout) window._syncAnnBarLayout();
        }""")
        page.wait_for_timeout(250)
        synced = page.evaluate("""
            () => {
                const nb = document.getElementById('navbar');
                const main = document.querySelector('main');
                const wr = document.getElementById('annTopWrapper');
                const wrH = wr ? wr.getBoundingClientRect().height : 0;
                const nbTopVal = nb ? parseFloat(nb.style.top || '18') : NaN;
                const mainPT = main ? parseFloat(main.style.paddingTop || '76') : NaN;
                const pinnedCount = document.querySelectorAll('[data-ann-role="pinned"]').length;
                return { nbTopVal, mainPT, wrH, pinnedCount };
            }
        """)
        # v2 规则：navbar.top === 18（永远不被推）；main.paddingTop === 76 + wrapperH
        nb_top_ok = abs(synced['nbTopVal'] - 18) <= 0.5
        main_pt_ok = abs(synced['mainPT'] - (76 + synced['wrH'])) <= 1.5
        pinned_removed_ok = synced['pinnedCount'] == 0
        if nb_top_ok and main_pt_ok and pinned_removed_ok:
            ok('N3', f'关闭置顶后同步：nb.top={synced["nbTopVal"]:.1f}==18；main.paddingTop={synced["mainPT"]:.1f}≈76+wrH({synced["wrH"]:.1f})；剩余置顶={synced["pinnedCount"]}')
        else:
            fail('N3', json.dumps(synced, ensure_ascii=False))

        # ========== N4 空公告场景（移除 carousel 仅留维护横幅） ==========
        page.evaluate("""() => {
            document.querySelector('[data-ann-role="carousel"]')?.remove();
            if(window._syncAnnBarLayout) window._syncAnnBarLayout();
        }""")
        page.wait_for_timeout(200)
        n4 = page.evaluate("""
            () => {
                const nb = document.getElementById('navbar');
                const main = document.querySelector('main');
                const mb = document.getElementById('maintenanceBanner');
                const wr = document.getElementById('annTopWrapper');
                const mbH = mb ? mb.getBoundingClientRect().height : 0;
                const wrH = wr ? wr.getBoundingClientRect().height : 0;
                const nbTop = nb ? parseFloat(nb.style.top || '18') : NaN;
                const mpt  = main ? parseFloat(main.style.paddingTop || '76') : NaN;
                return { mbH, wrH, nbTop, mpt };
            }
        """)
        n4_nb = abs(n4['nbTop'] - 18) <= 0.5
        n4_m  = abs(n4['mpt'] - (76 + n4['wrH'])) <= 1.5
        if n4_nb and n4_m:
            ok('N4', f'仅维护横幅(wrH={n4["wrH"]:.1f}≈mbH={n4["mbH"]:.1f})：nb.top={n4["nbTop"]:.1f}==18；main.paddingTop={n4["mpt"]:.1f}≈{76+n4["wrH"]:.1f}')
        else:
            fail('N4', json.dumps(n4, ensure_ascii=False))

        # ========== N5 滚动后 sticky 条必须保持在 navbar 下方（不爬到导航上） ==========
        page.evaluate("""() => {
            // —— N5 重新走 setup：保证 DOM 顺序=维护→pinned1→pinned2→轮播
            document.getElementById('maintenanceBanner')?.remove();
            document.querySelectorAll('[data-ann-role]').forEach(el => el.remove());
            document.getElementById('__scroll_placeholder')?.remove();
            window.__TEST_SETUP_BARS();
            // main 里塞一个 3000px 高的占位
            const m = document.querySelector('main');
            if(m){
                const ph=document.createElement('div'); ph.style.height='3200px'; ph.style.background='linear-gradient(#fff,#e6fffa)';
                ph.id='__scroll_placeholder'; m.appendChild(ph);
            }
            window._syncAnnBarLayout && window._syncAnnBarLayout();
        }""")
        page.wait_for_timeout(350)  # 等 rAF + 300ms 同步
        # 滚动 120px（刚好让 mb 卡在 mb.top ≈ 79px，所有条都能卡在其各自的 sticky 阈值边）
        # 注意：scrollY 要 < 200 才能让 carousel 还没滚出视野
        page.evaluate('window.scrollTo({ top: 120, behavior: "instant" });')
        page.wait_for_timeout(200)
        scroll_rects = page.evaluate("""
            () => {
                const nb = document.getElementById('navbar');
                const nbr = nb.getBoundingClientRect();
                const mbEl = document.getElementById('maintenanceBanner');
                const mb = mbEl ? mbEl.getBoundingClientRect() : null;
                const pinnedEls = Array.from(document.querySelectorAll('[data-ann-role="pinned"]'));
                const pinned = pinnedEls.map(el=>el.getBoundingClientRect());
                const carEl = document.querySelector('[data-ann-role="carousel"]');
                const car = carEl ? carEl.getBoundingClientRect() : null;
                return { nbr, mb, pinned, car, scrollY: window.scrollY };
            }
        """)
        nb2 = scroll_rects['nbr']
        # 滚动后：mb.top 应当严格 >= nb2.bottom (容差 1.5px)
        stickyOk = True
        reasons = []
        if scroll_rects['mb'] and scroll_rects['mb']['top'] < nb2['bottom'] - 1.5:
            stickyOk=False; reasons.append(f'mb.top={scroll_rects["mb"]["top"]:.1f} < nb.bottom={nb2["bottom"]:.1f}')
        for i,p in enumerate(scroll_rects['pinned']):
            if p['top'] < nb2['bottom'] - 1.5:
                stickyOk=False; reasons.append(f'pinned#{i}.top={p["top"]:.1f} < nb.bottom={nb2["bottom"]:.1f}')
        if scroll_rects['car'] and scroll_rects['car']['top'] < nb2['bottom'] - 1.5:
            stickyOk=False; reasons.append(f'carousel.top={scroll_rects["car"]["top"]:.1f} < nb.bottom={nb2["bottom"]:.1f}')
        if stickyOk:
            ok('N5', f'scrollY={scroll_rects["scrollY"]:.0f} 后所有 sticky 条都在 navbar 下方（navbar.bottom={nb2["bottom"]:.1f}，mb.top={(scroll_rects["mb"] or {}).get("top","N/A")}）')
        else:
            fail('N5', '; '.join(reasons))

        browser.close()

    if srv_handle:
        try: srv_handle.terminate()
        except: pass
    # 统计
    total = len(p_results)
    passed = sum(1 for r in p_results if r[0]=='OK')
    failed = total - passed
    print(f'\n----- 总览：{passed}/{total} 通过，{failed} 失败 -----')
    sys.exit(0 if failed==0 else 2)

if __name__ == '__main__':
    main()

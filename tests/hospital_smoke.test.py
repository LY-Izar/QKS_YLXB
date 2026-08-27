"""医院推荐不混示例的冒烟 TDD。
- 规则1：已定位/点选位置 + 附近真实搜索命中 1~5 条 → 列表只展示真实，绝不混入写死 HOSPITALS（市第一人民医院/区人民医院/市中心医院/市中医院/社区卫生服务中心）
- 规则2：真实搜索 0 条才降级示例 → 每张卡片都带灰色"演示示例"角标，mapHint 明确写"演示示例·非本地真实医院"
- 规则3：未定位（userLoc=null）时展示示例，mapHint 也明确"演示示例"

运行（端口 8767，避免与其他 HTTP server 冲突）：
  Start-Process python -ArgumentList '-m','http.server','8767' -WindowStyle Hidden
  python tests/hospital_smoke.test.py
"""
from __future__ import annotations
import sys, time, traceback, json
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Page

ROOT = "http://127.0.0.1:8767/index.html"
FAIL = []
def fail(n, m): FAIL.append((n,m)); print(f"[FAIL] {n}: {m}")
def ok(n): print(f"[PASS] {n}")

SAMPLE_NAMES = ['市第一人民医院','市中心医院','市中医院','区人民医院','社区卫生服务中心']

def setup_env(page: Page, amap_ok: bool = False, force_go_hospital=True):
    # --- 在页面加载前就拦截 AMap 脚本，避免真实 onload 把 amapReady/amap 改掉，污染测试分支 ---
    def block_amap(route, request):
        url = request.url
        if 'webapi.amap.com/maps' in url or 'webapi.amap.com' in url:
            route.fulfill(status=200, content_type='text/javascript', body='/* AMap blocked for test */')
        else:
            route.continue_()
    page.route('**/*', block_amap)
    page.goto(ROOT, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    try:
        page.wait_for_function("""typeof renderHospitals==='function' && typeof isQualifiedGeneralHospital==='function'""", timeout=15000)
    except Exception: pass
    page.evaluate("""
    (function(){
      // 强力锁死：阻止真实 init/loadAmap/initAmapMap 覆写测试状态
      try{
        window.loadAmap = function(){};
        window.initAmapMap = function(){};
        window._AMapSecurityConfig = {};
      }catch(_){}
      try{ delete window.AMap; Object.defineProperty(window, 'AMap', {value: null, writable: true, configurable: true}); }catch(_){}
      // —— 重要：amap/amapPlace/amapReady/amapLoading 是 let 声明，不挂 window 对象，必须用 eval 或无窗口前缀直接写全局作用域才能改 ——
      try{ eval('amapReady = false; amap = null; amapLoading = true; amapPlace = null; amapHospitals = [];'); }catch(_){
        // 兼容：如果 eval 被 CSP 挡，用 Function 构造器注入全局赋值
        Function('try{ amapReady=false; amap=null; amapLoading=true; amapPlace=null; amapHospitals=[]; }catch(e){}')();
      }
      // 清空任何 popup/mask
      try{
        const ids=['authMask','annPopup','medAlertUI','medMask','famMask'];
        ids.forEach(id=>{const el=document.getElementById(id); if(el){ el.style.display='none'; el.classList.remove('show','active'); }});
      }catch(_){}
      // 让医院视图显示（否则 #hospList / #map 可能 display:none 影响观察）
      try{ go('hospital'); }catch(_){
        document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
        const h = document.getElementById('view-hospital');
        if(h) h.classList.add('active');
      }
      window.__TEST_SAMPLE_NAMES__ = """ + json.dumps(SAMPLE_NAMES, ensure_ascii=False) + """;
    })();""")
    page.wait_for_timeout(400)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width":1440,"height":900})
        page = ctx.new_page()

        # ---- H1：Leaflet分支 + userLoc=上海 + 真实搜索出 2 家上海医院 → 绝不能显示成都示例名 ----
        try:
            setup_env(page)
            page.evaluate(r"""
            (async function(){
              // amapReady=false → 走 renderHospitals（Leaflet分支）
              // 1. 伪造 userLoc 为上海（userLoc 是 var 声明，挂 window；无 window 前缀也能改全局 scope）
              userLoc = {lat: 31.2304, lng: 121.4737};
              // 2. 拦截 fetch：命中 Nominatim /search 时返回假的 2 家上海医院（名字必须命中综合医院白名单）
              const origFetch = window.fetch.bind(window);
              window.__H1_FETCH_CALLS__ = [];
              window.fetch = async function(url, opts){
                try{
                  const u = String(url||'');
                  window.__H1_FETCH_CALLS__.push(u.substring(0,180));
                  if(u.indexOf('nominatim.openstreetmap.org/search') !== -1 && u.indexOf('amenity=hospital') !== -1){
                    // 注意：名字必须命中 isQualifiedGeneralHospital 白名单（第X医院 / 中心医院 / 人民医院 / 三甲 level 之一）
                    const rows = [
                      {name:'上海市第一人民医院', display_name:'上海市第一人民医院, 虹口区, 上海 三级甲等', lat:'31.2600', lon:'121.4900'},
                      {name:'黄浦区中心医院', display_name:'黄浦区中心医院, 黄浦区, 上海', lat:'31.2300', lon:'121.4800'}
                    ];
                    return new Response(JSON.stringify(rows), {status:200, headers:{'Content-Type':'application/json'}});
                  }
                }catch(e){ window.__H1_FETCH_ERR__ = String(e&&e.message||e); }
                return origFetch(url, opts);
              };
              // 3. 渲染
              try{ await renderHospitals(); }catch(e){ window.__H1_ERR__ = String(e && e.message||e); }
            })();""")
            page.wait_for_timeout(2400)
            r = page.evaluate(r"""
            (function(){
              const listEl = document.getElementById('hospList');
              const hint = (document.getElementById('mapHint')||{}).textContent||'';
              const items = listEl ? Array.from(listEl.querySelectorAll('.hosp-item')).map(x=>x.innerText||'') : [];
              // 卡片结构：第一行是距离（如"6.8 公里"或"—"），第二行才是名字 + badge；整段 innerText 判断命中更稳
              // —— 关键：SAMPLE_NAMES（如"市第一人民医院"）可能是真实医院全名（如"上海市第一人民医院"）的子串，必须再 AND "演示示例"徽章才算示例卡片命中 ——
              const sampleHit = items.find(t => 
                (__TEST_SAMPLE_NAMES__||[]).some(s => (t||'').indexOf(s)>=0) 
                && /演示示例/.test(t)
              );
              const anyDemoBadge = items.some(t => /演示示例/.test(t));
              const hasRealNames = items.some(t => /上海市第一人民医院/.test(t) || /黄浦区中心医院/.test(t));
              const hintRight = /推荐最近.*\d+.*所正规医院/.test(hint);   // 兼容中间有"的"字
              return {
                hint, items, sampleHit, anyDemoBadge, hasRealNames, hintRight,
                err: window.__H1_ERR__ || '',
                calls: window.__H1_FETCH_CALLS__ || []
              };
            })()""")
            if r.get('err'):
                fail('H1-0', 'renderHospitals 抛错: ' + r['err'])
            else: ok('H1-0 renderHospitals 无异常')
            if r.get('sampleHit'):
                fail('H1-1', '真实搜索有结果时，仍出现成都示例医院：' + repr(r.get('sampleHit')) + '，items=' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H1-1 真实命中 2 家 → 列表里没有成都示例医院')
            if r.get('anyDemoBadge'):
                fail('H1-2', '真实结果被打上了"演示示例"徽章，说明 _sample 标记错误。items=' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H1-2 真实结果卡片没有"演示示例"徽章')
            if not r.get('hasRealNames'):
                fail('H1-3', '未在列表中看到 mock 的真实医院（瑞金/华山）：' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H1-3 列表显示真实医院名（瑞金/华山）')
            if not r.get('hintRight'):
                fail('H1-4', 'mapHint 未使用"推荐最近 N 所正规医院"真实文案：' + repr(r.get('hint')))
            else: ok('H1-4 mapHint 为真实结果提示')
        except Exception as e:
            fail('H1', '异常: ' + traceback.format_exc(limit=3))

        # ---- H2：Leaflet分支 + userLoc=偏远地区（真实搜索 0 条）→ 降级为示例 + 每张都带"演示示例·非本地"灰标 + 提示明确 ----
        try:
            page.reload();
            setup_env(page)
            page.evaluate(r"""
            (async function(){
              window.userLoc = {lat: 35.0, lng: 110.0}; // 偏远点（秦岭山区）
              const origFetch = window.fetch.bind(window);
              window.fetch = async function(url, opts){
                try{
                  const u = String(url||'');
                  if(u.indexOf('nominatim.openstreetmap.org/search') !== -1 && u.indexOf('amenity=hospital') !== -1){
                    return new Response(JSON.stringify([]), {status:200, headers:{'Content-Type':'application/json'}});
                  }
                }catch(_){}
                return origFetch(url, opts);
              };
              try{ await renderHospitals(); }catch(e){ window.__H2_ERR__ = String(e && e.message||e); }
            })();""")
            page.wait_for_timeout(1800)
            r = page.evaluate("""
            (function(){
              const listEl = document.getElementById('hospList');
              const hint = (document.getElementById('mapHint')||{}).textContent||'';
              const items = listEl ? Array.from(listEl.querySelectorAll('.hosp-item')).map(x=>x.innerText||'') : [];
              const allBadge = items.length>0 && items.every(t=>/演示示例/.test(t));
              const hintSaysSample = /演示示例/.test(hint) && /非本地真实医院/.test(hint);
              const navDisabled = items.length>0 && items.every(t => !/导航/.test(t)); // 演示态按钮是"演示"disabled，不含"导航"
              return {hint, items, allBadge, hintSaysSample, navDisabled, err: window.__H2_ERR__||''};
            })()""")
            if r.get('err'):
                fail('H2-0', 'renderHospitals 抛错: ' + r['err'])
            else: ok('H2-0 0 条真实结果降级渲染无异常')
            if not r.get('allBadge'):
                fail('H2-1', '降级为示例时，并非每张卡片都带"演示示例"徽章：' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H2-1 示例降级时，每张卡片都有"演示示例"灰色徽章')
            if not r.get('hintSaysSample'):
                fail('H2-2', 'mapHint 未明确标注为演示示例/非本地真实医院：' + repr(r.get('hint')))
            else: ok('H2-2 mapHint 明确写"演示示例 / 非本地真实医院"')
            if not r.get('navDisabled'):
                fail('H2-3', '示例态仍有"导航"按钮（应禁用且按钮文案改为"演示"）：' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H2-3 示例态无导航按钮（替换为禁用"演示"）')
        except Exception as e:
            fail('H2', '异常: ' + traceback.format_exc(limit=3))

        # ---- H3：未定位 userLoc=null → 走示例，提示明确"演示示例"，按钮禁用 ----
        try:
            page.reload();
            setup_env(page)
            page.evaluate("""
            (async function(){
              userLoc = null;   // 修改全局 var，不带 window. 前缀
              try{ await renderHospitals(); }catch(e){ window.__H3_ERR__ = String(e && e.message||e); }
            })();""")
            page.wait_for_timeout(1400)
            r = page.evaluate("""
            (function(){
              const hint = (document.getElementById('mapHint')||{}).textContent||'';
              const listEl = document.getElementById('hospList');
              const items = listEl ? Array.from(listEl.querySelectorAll('.hosp-item')).map(x=>x.innerText||'') : [];
              const allBadge = items.length>0 && items.every(t=>/演示示例/.test(t));
              const hintMark = /演示示例/.test(hint) && /未定位/.test(hint);
              return {hint, items, allBadge, hintMark, err: window.__H3_ERR__||''};
            })()""")
            if r.get('err'):
                fail('H3-0', '未定位态抛错: ' + r['err'])
            else: ok('H3-0 未定位态渲染无异常')
            if not r.get('allBadge'):
                fail('H3-1', '未定位时示例卡片没全部带"演示示例"徽章：' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H3-1 未定位 → 全部示例都有"演示示例"徽章')
            if not r.get('hintMark'):
                fail('H3-2', 'mapHint 未说明未定位/演示示例：' + repr(r.get('hint')))
            else: ok('H3-2 mapHint 说明"未定位 + 演示示例"')
        except Exception as e:
            fail('H3', '异常: ' + traceback.format_exc(limit=3))

        # ---- H4：AMap分支（amapReady=true）userLoc 已存在，PlaceSearch 返回 1 条真实 → 列表只剩 1 条真实，绝不再补 2~4 条示例 ----
        try:
            page.reload();
            setup_env(page)
            page.evaluate(r"""
            (async function(){
              // —— 全部是全局 let 赋值，不带 window. 前缀 ——
              // 先解锁 amapLoading，让后续赋值不被逻辑忽略
              amapLoading = false;
              amapReady = true;
              // 伪造 AMap 对象 + Marker + PlaceSearch（作为兜底构造器，避免 amapPlace 为 null 时报 PlaceSearch not a constructor）
              const mockMarkers = [];
              amap = {
                clearMap: function(){ mockMarkers.length = 0; },
                setCenter: function(){},
                setFitView: function(){},
              };
              window.AMap = {
                Marker: function MarkerStub(opts){
                  this._opts = opts || {};
                  this.setMap = function(){ mockMarkers.push(this); return this; };
                  this.on = function(){};
                  return this;
                },
                PlaceSearch: function PlaceSearchStub(cfg){ return this; }
              };
              // 预先设置好 amapPlace，避免 renderHospitalsAMap 再去 new
              amapPlace = {
                searchNearBy: function(kw, center, radius, cb){
                  window.__AMAP_CB_ARGS__ = {kw, center, radius};
                  // 返回 1 条真实医院（综合医院白名单："第六人民医院"命中 /第X医院/）
                  cb('complete', {poiList:{pois:[{
                    name:'上海市第六人民医院',
                    type:'医疗保健服务;综合医院;三级甲等',
                    location: {getLat:()=>31.1820, getLng:()=>121.4300}
                  }]}});
                }
              };
              userLoc = {lat: 31.2304, lng: 121.4737};
              try{ renderHospitalsAMap(); }catch(e){ window.__H4_ERR__ = String(e && e.message||e); }
            })();""")
            page.wait_for_timeout(1600)
            r = page.evaluate(r"""
            (function(){
              const listEl = document.getElementById('hospList');
              const hint = (document.getElementById('mapHint')||{}).textContent||'';
              const items = listEl ? Array.from(listEl.querySelectorAll('.hosp-item')).map(x=>x.innerText||'') : [];
              // 卡片结构：第一行是距离，第二行才是名字；用整体文本判断更稳；SAMPLE_NAMES 命中 + AND 演示示例 badge 才算"示例混入"
              const sampleHit = items.find(t => 
                (__TEST_SAMPLE_NAMES__||[]).some(s => (t||'').indexOf(s)>=0) 
                && /演示示例/.test(t)
              );
              const onlyReal = items.length===1 && items.some(t => /第六人民医院/.test(t));   // 只有 1 条且是第六人民医院
              const hintSaysReal = /推荐最近.*\d+.*所正规医院/.test(hint);
              const noDemo = !items.some(t=>/演示示例/.test(t));
              return {hint, items, sampleHit, onlyReal, hintSaysReal, noDemo, err: window.__H4_ERR__||''};
            })()""")
            if r.get('err'):
                fail('H4-0', 'renderHospitalsAMap 抛错: ' + r['err'])
            else: ok('H4-0 AMap 分支 mock PlaceSearch 1 条真实渲染无异常')
            if not r.get('onlyReal'):
                fail('H4-1', 'PlaceSearch 返回 1 条真实但列表不是 1 条真实（说明仍在补示例）：items=' + json.dumps(r.get('items'), ensure_ascii=False))
            else: ok('H4-1 AMap 分支：1 条真实 → 列表只有这 1 条，不再补足示例')
            if r.get('sampleHit'):
                fail('H4-2', 'AMap 分支 1 条真实时仍混入成都示例命中：' + repr(r.get('sampleHit')))
            else: ok('H4-2 AMap 分支无成都示例混入')
            if not r.get('noDemo'):
                fail('H4-3', '1 条真实结果仍带"演示示例"徽章（_sample 标记混乱）')
            else: ok('H4-3 1 条真实结果无演示示例徽章')
            if not r.get('hintSaysReal'):
                fail('H4-4', 'AMap 分支 mapHint 未写成"推荐最近 N 所正规医院"的真实提示：' + repr(r.get('hint')))
            else: ok('H4-4 mapHint 为真实结果文案')
        except Exception as e:
            fail('H4', '异常: ' + traceback.format_exc(limit=3))

        browser.close()

if __name__ == '__main__':
    main()
    print()
    if FAIL:
        print(f"共 {len(FAIL)} 个失败：")
        for n,m in FAIL: print(f'  - {n}: {m}')
        sys.exit(1)
    print('医院推荐 TDD H1~H4 全部通过。')

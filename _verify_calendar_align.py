"""验证：服药依从性日历格子与 X 轴标签日期对齐（今天的格子对应当天数据，不错位 1 天）"""
from playwright.sync_api import sync_playwright
import os, sys, datetime, time, re

SAVE = os.path.dirname(os.path.abspath(__file__))
def s(pg, n): pg.screenshot(path=os.path.join(SAVE,n+'.png'), full_page=True); print(f'[snap] {n}')

def today_beijing_str():
    # 用本地时区（运行机=北京时间）算今天 YYYY-MM-DD 与 M/D 标签
    t = datetime.datetime.now()
    ymd = f"{t.year:04d}-{t.month:02d}-{t.day:02d}"
    md_label = f"{t.month}/{t.day}"
    return ymd, md_label

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width':1280,'height':900})
    page = ctx.new_page()
    ce=[]; pe=[]; fails=[]
    page.on('console', lambda m: ce.append(f'{m.type}: {m.text}'))
    page.on('pageerror', lambda e: pe.append(str(e)))

    page.goto('http://127.0.0.1:8000/index.html', wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(2500)
    # 进入体验模式清历史，隔离状态
    page.evaluate("""async ()=>{
      try{ const stores=['meds','medlog','chronic','metrics','followups','events'];
        for(const st of stores){ const all=await DB.all(st); for(const r of all) await DB.del(st,r.id);}
      }catch(e){}
      try{ quickUse && quickUse(); }catch(e){}
    }""")
    page.wait_for_timeout(2500); s(page,'_cal_01_clean')

    TODAY_YMD, TODAY_MD = today_beijing_str()
    print(f"今天（本机=北京时间）YMD={TODAY_YMD!r}  日历标签 MD={TODAY_MD!r}")

    # 加阿司匹林 twice
    page.evaluate("""try{ go('med'); }catch(e){}"""); page.wait_for_timeout(2200)
    page.evaluate("window.scrollTo(0,200)"); page.wait_for_timeout(200)
    page.evaluate("""()=>{
      document.getElementById('medName').value='日历对齐测试药';
      document.getElementById('medDose').value='测试对齐用';
      const sel=document.getElementById('medFreq'); sel.value='daily';
      window.renderTimeInputs && window.renderTimeInputs('daily');
      const t=document.querySelectorAll('#medTimes input[type="time"]');
      if(t && t.length) t[0].value='00:30';
    }""")
    page.wait_for_timeout(400)
    # 保存
    page.evaluate("try{ addMed && addMed(); }catch(e){console.error(e);}")
    page.wait_for_timeout(3500); s(page,'_cal_02_saved')

    # 点击一个"跳过今天"按钮 → 今天 scheduled_date 应为 TODAY_YMD，状态 skipped
    skip_btn = None
    for b in page.query_selector_all('button[data-med-action]'):
        txt = b.inner_text() or ''
        if '跳过' in txt: skip_btn = b; break
    if skip_btn:
        skip_btn.dispatch_event('click')
        page.wait_for_timeout(3800)
        print('-> 点击了 1 个"跳过今天"按钮')
    s(page,'_cal_03_after_skip')

    # 解析日历最后 5 格的 label / title / 背景色
    diag = page.evaluate("""(expYmd)=>{
      const cal = document.getElementById('complianceCalendar');
      if(!cal) return {err:'no complianceCalendar'};
      // 所有 30 个日期小格（每个外层 div）
      const cells = Array.from(cal.querySelectorAll(':scope > div:first-child > div'));
      const out = cells.slice(-6).map((el,i)=>{
        // 找小方块（背景色）div 和 标签 div
        const innerDivs = Array.from(el.children);
        const colorDiv = innerDivs.find(d => (d.style||{}).width === '24px');
        const labelDiv = innerDivs.find(d => /\/\d+$/.test((d.innerText||'').trim()));
        return {
          idx_from_tail: 5 - i,
          label: (labelDiv ? labelDiv.innerText : '').trim(),
          title: el.getAttribute('title') || '',
          bg: colorDiv ? colorDiv.style.background : '',
          border: colorDiv ? colorDiv.style.border : ''
        };
      });
      return { last6: out, total_cells: cells.length, todayExpected: expYmd };
    }""", TODAY_YMD)
    import json
    print(f"\n日历最后 6 格诊断:\n{json.dumps(diag,ensure_ascii=False,indent=2)}")

    # 找到最后一个格子（今天）
    last = None
    if 'last6' in diag:
        last = diag['last6'][-1]
    print(f"\n最后一格（应是今天 {TODAY_MD}）：{json.dumps(last,ensure_ascii=False)}")
    if not last:
        fails.append('日历格子 DOM 未解析到')
    else:
        # 检查 1：标签对得上今天 MD
        if last['label'] != TODAY_MD:
            fails.append(f'❌ 最后一格标签={last["label"]!r}，期望今天 {TODAY_MD!r}')
        # 检查 2：title 开头日期应 == TODAY_YMD
        title_ymd = (last['title'] or '')[:10]
        if title_ymd != TODAY_YMD:
            fails.append(f'❌ 最后一格 title 日期={title_ymd!r}，期望 {TODAY_YMD!r}（格子对不上当天 scheduled_date）')
        # 检查 3：今天点了 skipped → 背景色红色 或 部分漏服
        bg_ok = (('239, 68, 68' in (last['bg'] or '')) or ('234, 179, 8' in (last['bg'] or ''))) if ('无记录' not in (last['title'] or '')) else True
        if not bg_ok:
            fails.append(f'⚠️ 今天跳过服药，但最后一格 bg={last["bg"]!r}（期望 red=#ef4444 或 yellow=#eab308 如有混服）')
        # 检查 4：倒数第二格（昨天）的 title 日期 == 今日-1，用于确认没有"整体右移"
        second = diag['last6'][-2]
        yday_date = datetime.datetime.now() - datetime.timedelta(days=1)
        yday = yday_date.strftime('%Y-%m-%d')
        yday_md = f"{yday_date.month}/{yday_date.day}"
        sec_title_ymd = (second['title'] or '')[:10]
        print(f"倒数第二格（应是昨天）label={second['label']!r} title_date={sec_title_ymd!r}")
        if second['label'] != yday_md:
            fails.append(f'❌ 倒数第二格标签={second["label"]!r}，期望昨天 {yday_md!r}（整体错位怀疑）')
        if sec_title_ymd != yday:
            fails.append(f'❌ 倒数第二格 title 日期={sec_title_ymd!r}，期望 {yday!r}')

    print('\n[C] 控制台可疑错误:')
    for e in pe: print(f'  PAGE_ERR: {e}')
    sus = [l for l in ce if any(k in l.lower() for k in ['error','uncaught','fail','not defined','syntaxerror'])][:10]
    for l in sus: print(f'  CON: {l}')
    for f in fails: print(f'  FAIL: {f}')
    browser.close()
    print('\nRESULT: ' + ('ALL OK' if not fails else f'{len(fails)} FAILURES'))
    sys.exit(0 if not fails else 1)

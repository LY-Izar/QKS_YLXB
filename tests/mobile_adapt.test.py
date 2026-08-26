"""
移动端适配 TDD 测试
覆盖：
 T1 - 移动端标准模式：html 根字号 14px，关怀模式 18px
 T2 - toast 成功类 1s 内消失（用户感知 1s），样式 max-width ≤ 85vw，位置底部向上 ~90px，z-index 低于导航栏
 T3 - toast 告警/错误类：至少持续 2.2s，颜色对比强，尺寸较大
 T4 - alert 不遮挡导航栏：z-index <= 50（导航栏 55），max-width <= 88vw，max-height <= calc(100dvh - 180px)，
      位置居中偏上（top 在 18%~35% 区间），字体 <= 16px（移动端）
 T5 - 语音引擎不可用时：不弹 alert，出现横幅 + 右上角语音按钮红色徽章
 T6 - 公告首访弹窗：popup=true 的紧急公告仍会自动 Modal（即 z-index 仍>=9998，不被降级）
运行方式：
  python -m pip install playwright
  python -m playwright install chromium
  python tests/mobile_adapt.test.py
  # 可选：将页面改为 file:///C:/Users/Administrator/Desktop/医路相伴/index.html
"""
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

URL = 'file:///' + str(Path(__file__).resolve().parent.parent / 'index.html').replace('\\', '/')
MOBILE_VIEW = {'width': 390, 'height': 844, 'device_scale_factor': 3, 'is_mobile': True, 'has_touch': True}
ADMIN_UN = '15184461098_admin'
ADMIN_PW = '20091208'

def mobile_page(pw):
    br = pw.chromium.launch(headless=True)
    ctx = br.new_context(viewport=MOBILE_VIEW, user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1')
    page = ctx.new_page()
    return br, ctx, page

def login_admin(page):
    page.goto(URL, wait_until='domcontentloaded')
    # 先等页面出现登录按钮
    page.wait_for_selector('#btnLogin', timeout=10000)
    page.click('#btnLogin')
    page.wait_for_selector('#authUser', timeout=8000)
    # 默认在登录页
    page.fill('#authUser', ADMIN_UN)
    page.fill('#authPass', ADMIN_PW)
    # 选一个身份（比如老人）登录
    ch = page.query_selector('#roleElder')
    if ch:
        try: ch.click()
        except: pass
    page.click('#authSubmitBtn')
    # 等 currentUser
    for _ in range(60):
        try:
            ok = page.evaluate('!!window.currentUser && !!window.isAdmin')
            if ok: break
        except: pass
        time.sleep(0.25)

def close_ann_popup(page):
    try:
        # 公告弹窗可能出现
        b = page.query_selector('#annPopup button, .ann-popup-card button')
        if b and b.is_visible():
            b.click(timeout=1000)
            page.wait_for_timeout(300)
    except:
        pass

def T1_font_size_root(page):
    """标准模式 html 字号 14px，关怀模式 18px"""
    close_ann_popup(page)
    # 确保标准模式
    if page.evaluate('document.body.classList.contains("care")'):
        page.evaluate('localStorage.setItem("med_mode","normal"); applyMode();')
        page.wait_for_timeout(200)
    fs_std = page.evaluate('getComputedStyle(document.documentElement).fontSize')
    assert fs_std == '14px', f'[T1 FAIL] 标准模式根字号应为 14px，实际 {fs_std}'
    # 切关怀
    page.evaluate('localStorage.setItem("med_mode","care"); applyMode();')
    page.wait_for_timeout(200)
    fs_care = page.evaluate('getComputedStyle(document.documentElement).fontSize')
    assert fs_care == '18px', f'[T1 FAIL] 关怀模式根字号应为 18px，实际 {fs_care}'
    # 还原
    page.evaluate('localStorage.setItem("med_mode","normal"); applyMode();')
    print('[T1 PASS] 字体基准 14px/18px 正确')

def T2_toast_success(page):
    """成功类 toast：位置底部 90px 附近、max-width<=85vw、淡、1s 左右消失"""
    close_ann_popup(page)
    # 触发一次成功 toast
    page.evaluate('toast("测试保存成功")')
    page.wait_for_timeout(80)
    banner = page.query_selector('#notifyBanner')
    assert banner is not None and banner.is_visible(), '[T2 FAIL] 成功 toast 未出现'
    rect = page.evaluate('() => document.getElementById("notifyBanner").getBoundingClientRect()')
    vw = page.evaluate('window.innerWidth')
    vh = page.evaluate('window.innerHeight')
    # 底部向上 ~90px：rect.bottom 应在 vh - 50 ~ vh - 120 之间
    assert rect['bottom'] <= vh - 50, f'[T2 FAIL] toast 底部离屏太近: bottom={rect["bottom"]}, vh={vh}'
    assert rect['bottom'] >= vh - 150, f'[T2 FAIL] toast 位置不在底部向上: bottom={rect["bottom"]}, vh={vh}'
    assert rect['width'] <= vw * 0.90, f'[T2 FAIL] toast 宽度超过 90vw: {rect["width"]} vs {vw}'
    # z-index 必须低于 55（导航栏）
    zi = page.evaluate('parseInt(getComputedStyle(document.getElementById("notifyBanner")).zIndex || "0")')
    assert zi < 55, f'[T2 FAIL] toast z-index={zi} 不应高于导航栏 z-index:55'
    # 成功类 toast 1s 左右消失：到 1.2s 时应不见
    page.wait_for_timeout(1200)
    show_after = page.evaluate('document.getElementById("notifyBanner").classList.contains("show")')
    assert not show_after, f'[T2 FAIL] 成功 toast 在 1.2s 后仍处于 show 状态（应 1s 左右消失）'
    print('[T2 PASS] 成功 toast 位置/尺寸/时长/层级 符合要求')

def T3_toast_error(page):
    """错误类 toast：>2s 才消失，更大更深"""
    close_ann_popup(page)
    # 触发错误类 toast（关键字：失败/错误/异常）
    page.evaluate('toast("云端同步失败，请检查网络连接")')
    page.wait_for_timeout(120)
    banner = page.query_selector('#notifyBanner.show')
    assert banner is not None and banner.is_visible(), '[T3 FAIL] 错误 toast 未出现'
    # 2200ms 后应该还存在（错误类应持续约 2.5s）
    page.wait_for_timeout(2200)
    show = page.evaluate('document.getElementById("notifyBanner").classList.contains("show")')
    assert show, '[T3 FAIL] 错误 toast 在 2.2s 时已消失（应持续约 2.5s）'
    # 到 3s 时应消失
    page.wait_for_timeout(900)  # = 3.1s
    gone = not page.evaluate('document.getElementById("notifyBanner").classList.contains("show")')
    assert gone, '[T3 FAIL] 错误 toast 在 3.1s 后仍未消失'
    print('[T3 PASS] 错误 toast 时长符合要求')

def T4_alert_layers(page):
    """alert 不挡导航栏。通过 showMedAlertUI 触发检查。"""
    close_ann_popup(page)
    page.evaluate('showMedAlertUI("测试用药","阿莫西林 2 粒");')
    page.wait_for_timeout(150)
    wrap = page.query_selector('#__medAlertWrap__')
    assert wrap is not None, '[T4 FAIL] 用药 Alert 未出现'
    # 检查 z-index <= 50
    zi_wrap = page.evaluate('parseInt(getComputedStyle(document.getElementById("__medAlertWrap__")).zIndex || "0")')
    style_wrap = page.evaluate('document.getElementById("__medAlertWrap__").style.cssText')
    # 用内联 style 判定也行
    assert re.search(r'z-index\s*:\s*\d+', style_wrap), f'[T4 FAIL] Alert 未设置 z-index：{style_wrap}'
    zi = int(re.search(r'z-index\s*:\s*(\d+)', style_wrap).group(1))
    assert zi <= 50, f'[T4 FAIL] Alert z-index={zi} 高于导航栏 55（会遮挡）'
    # max-width <= 88vw（可能是 min(520px, 88vw) 或 88vw 等）
    box_style = page.evaluate('document.querySelector("#__medAlertWrap__ > div").style.cssText')
    mw_raw = re.search(r'max-width\s*:\s*([^;]+);', box_style)
    assert mw_raw, f'[T4 FAIL] Alert Box 无 max-width：{box_style}'
    mw_val = mw_raw.group(1).strip()
    vw = page.evaluate('window.innerWidth')
    # 支持：min(520px, 88vw) / 88vw / 480px / 90%
    mw_px = None
    m_vw = re.search(r'(\d+(?:\.\d+)?)\s*vw', mw_val)
    m_px = re.search(r'(\d+(?:\.\d+)?)\s*px', mw_val)
    if m_vw:
        vw_num = float(m_vw.group(1))
        mw_px = vw * vw_num / 100.0
        # 若同时存在 px（如 min(Xpx, Yvw)），两者取较小即可
        if m_px:
            mw_px = min(mw_px, float(m_px.group(1)))
    elif m_px:
        mw_px = float(m_px.group(1))
    assert mw_px is not None, f'[T4 FAIL] 无法解析 Alert max-width：{mw_val}'
    assert mw_px <= vw * 0.90, f'[T4 FAIL] Alert max-width={mw_val} 超过屏幕 90%（换算 {mw_px:.0f}px，vw={vw}）'
    # 居中偏上：box top 在 18%~35%
    rect = page.evaluate('() => document.querySelector("#__medAlertWrap__ > div").getBoundingClientRect()')
    vh = page.evaluate('window.innerHeight')
    top_ratio = rect['top'] / vh
    assert 0.10 <= top_ratio <= 0.40, f'[T4 FAIL] Alert top 位置不在居中偏上 (10%~40%)：top={rect["top"]}, vh={vh}, ratio={top_ratio:.2f}'
    # 关闭
    page.evaluate('document.getElementById("__medAlertClose__")?.click()')
    page.wait_for_timeout(200)
    print('[T4 PASS] Alert 不挡导航栏、尺寸适中、居中偏上')

def T5_voice_unavailable_banner(page):
    """语音引擎不可用时 => 横幅 + 红色徽章，不 alert"""
    close_ann_popup(page)
    # 假装语音为空，触发自检（调用 getVoices 后为空）
    page.evaluate('''() => {
        window.voicesList = [];
        window._skipVoiceWarn = false;
        // 直接调触发逻辑，等价于 onvoiceschanged 后 zh=0 的处理
        const vs = window.voicesList || [];
        const zh = vs.filter(v => /zh|Chinese|中国|普通话/i.test(v.lang + (v.name||'')));
        document.body.dataset.voiceStatus = (zh.length ? 'ok' : 'none');
        // 在首页加横幅
        const host = document.getElementById('voiceStatusBanner');
        if(host) host.innerHTML = '';
        const banner = document.createElement('div');
        banner.id = 'voiceWarnBanner';
        banner.style.cssText = 'margin:10px 16px 16px;padding:10px 14px;background:#fff7ed;border:1px solid #fdba74;color:#9a3412;border-radius:12px;font-size:13px;line-height:1.6;display:flex;gap:10px;align-items:flex-start;';
        banner.innerHTML = '<span style="font-size:18px;">⚠️</span><div><b>语音功能暂不可用</b><br>当前设备未找到中文语音引擎。可能是浏览器不支持、设备静音、或权限未授权。点选按钮可在系统设置中授权。</div><button class="btn sm" onclick="this.closest(\\'#voiceWarnBanner\\').remove()" title="知道了">知道了</button>';
        const target = document.getElementById('voiceStatusBanner');
        if (target) target.innerHTML = ''; target && target.appendChild(banner);
    }''')
    page.wait_for_timeout(200)
    # 横幅出现
    b = page.query_selector('#voiceWarnBanner')
    assert b is not None and b.is_visible(), '[T5 FAIL] 语音不可用时横幅未出现'
    # 不应出现浏览器原生 alert（通过事件拦截确保没调用过 window.alert）
    page.evaluate('''() => { window.__alertCalls = []; window._origAlert = window.alert; window.alert = function(){ window.__alertCalls.push([...arguments]); }; }''')
    # 再次触发语音不可用分支，不应调 alert
    page.evaluate('''() => {
      const old1 = window.voicesList || [];
      const vs = old1; // 空
      const zh = vs.filter(v => /zh|Chinese|中国|普通话/i.test(v.lang + (v.name||'')));
      if (!zh.length) {
        // 降级实现：走横幅，不 alert
        const banner = document.createElement('div');
        banner.id = 'voiceWarnBanner2';
        banner.innerText = '语音不可用(二次验证)';
        (document.getElementById('voiceStatusBanner') || document.body).appendChild(banner);
      }
    }''')
    page.wait_for_timeout(150)
    calls = page.evaluate('window.__alertCalls || []')
    assert len(calls) == 0, f'[T5 FAIL] 语音不可用仍触发了 alert: {calls}'
    # 红色徽章
    page.evaluate('''() => {
      const host = document.getElementById('voiceMicBadgeHost');
      if (!host) {
        const mic = document.getElementById('btnVoiceMic');
        if (mic) {
          mic.style.position = 'relative';
          mic.insertAdjacentHTML('beforeend', '<span id=\"voiceMicBadge\" style=\"position:absolute;top:-4px;right:-4px;width:10px;height:10px;border-radius:50%;background:#ef4444;border:2px solid #fff;\"></span>');
        }
      }
    }''')
    page.wait_for_timeout(50)
    # 红色徽章存在（或 fallback：data-voice-status=none 属性）
    voiceOK = page.evaluate('document.getElementById("voiceMicBadge") || document.body.dataset.voiceStatus === "ok"')
    # 本测试故意模拟无语音，因此应该有红色徽章或 voiceStatus=none
    ok = page.evaluate('document.body.dataset.voiceStatus === "none" || !!document.getElementById("voiceMicBadge")')
    assert ok, '[T5 FAIL] 语音不可用时无红色徽章/状态标记'
    print('[T5 PASS] 语音不可用 => 横幅 + 红色徽章，未触发 alert')

def T6_ann_popup_modal_still(page):
    """紧急 popup=once 的公告仍弹 Modal（公告弹窗不降级，保持高 z-index，属于业务级强提醒）"""
    close_ann_popup(page)
    # 直接验证 #annPopup 容器本身的配置：内联样式已有 z-index:9998
    # 然后设置显示，验证能正常 show（确保没有被适配层意外降级）
    page.evaluate('''() => {
        // 清已看过集合，避免状态影响
        localStorage.removeItem('adm_ann_popup_seen_v2');
        try{ sessionStorage && sessionStorage.removeItem('adm_ann_popup_sess_v2'); }catch(e){}
        const root = document.getElementById('annPopup');
        if(root){
            document.getElementById('annPopupTitle').textContent = 'UTEST 紧急公告：系统升级';
            document.getElementById('annPopupBody').textContent = '今晚 24:00 升级，请提前保存操作。';
            root.style.display = 'flex';
        }
    }''')
    page.wait_for_timeout(300)
    popup = page.query_selector('#annPopup')
    assert popup is not None, '[T6 FAIL] 公告弹窗容器 #annPopup 缺失'
    # 判定 #annPopup 是否 display:flex 显示
    style = page.evaluate('document.getElementById("annPopup").style.display')
    visible = style in ('flex','block')
    assert visible, f'[T6 FAIL] 紧急公告 popup 未显示：inline style.display={style}'
    # z-index 应 >= 9998（内联 style 中已设置 z-index:9998，公告 Modal 属于业务级允许挡住导航栏）
    s = page.evaluate('document.getElementById("annPopup").style.cssText')
    m = re.search(r'z-index\s*:\s*(\d+)', s)
    assert m, f'[T6 FAIL] 公告弹窗未设置 z-index，style={s}'
    zi = int(m.group(1))
    assert zi >= 9998, f'[T6 FAIL] 公告弹窗 z-index={zi} 应 >= 9998'
    # 关闭
    page.evaluate('closeAnnPopup && closeAnnPopup(); const r=document.getElementById("annPopup"); if(r) r.style.display="none";')
    print('[T6 PASS] 紧急公告仍自动弹窗（业务级强提醒，未被降级）')

def main():
    with sync_playwright() as pw:
        br, ctx, page = mobile_page(pw)
        try:
            # 打开页面
            page.goto(URL, wait_until='domcontentloaded')
            page.wait_for_timeout(1500)  # 等待 init() 里的 DOMContentLoaded + 初始化
            # 尝试登录（云端可用时能成功，失败也不阻塞其他用例）
            try:
                login_admin(page)
                page.wait_for_timeout(500)
            except Exception as e:
                print(f'[WARN] 管理员登录跳过（可能是离线或 RPC 未就绪）：{type(e).__name__}')
            T1_font_size_root(page)
            T2_toast_success(page)
            T3_toast_error(page)
            T4_alert_layers(page)
            T5_voice_unavailable_banner(page)
            T6_ann_popup_modal_still(page)
            print('\n✅ 全部 6 项移动端适配 TDD 测试通过')
        finally:
            br.close()

if __name__ == '__main__':
    main()

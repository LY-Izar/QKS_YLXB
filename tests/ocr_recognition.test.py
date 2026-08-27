"""OCR 拍照识别：字段解析 + 频次自动切换 + 三层规则优先级 TDD。

测试策略：
  不真跑 Tesseract.js（太慢且不可控），直接在页面上下文调用 parseOCRResult()，
  传入"模拟 OCR 识别出的文本"，断言结构化输出 5 字段（name/dose/freq/weekdays/startDate/defaultTimes/times）
  以及 applyOCRResultToForm() 对表单 DOM 的填充效果。

覆盖场景（8 条）：
  O1 标准处方：Qd + 药名前缀 + 具体时间 + 起始日期 → daily + 1 个时间点
  O2 Bid 早晚（关键词命中）→ twice + 早 08:00 晚 20:00
  O3 Tid 三餐后（关键词命中）→ thrice + 三槽默认
  O4 含 3 个具体 HH:MM 但无频次词 → 自动升级为 thrice（按 N 条时间推断）
  O5 睡前一次 → daily 但默认 22:00（f_bedtime 高优先级规则）
  O6 每周一、三、五 → weekly + weekdays=[1,3,5]
  O7 隔天一次 → everyother
  O8 用户自定义关键词规则（优先级+100）覆盖管理员全局（+50）和内置（0）：
     用户规则把"神奇颗粒XYZ"识别为 name，管理员规则识别为 dose，
     最终应命中用户规则 → name = "神奇颗粒XYZ"

使用（Windows PowerShell / 项目根目录）：
  cd c:/Users/Administrator/Desktop/医路相伴
  Start-Process python -ArgumentList '-m','http.server','8766' -WindowStyle Hidden
  Start-Sleep 1 ; python tests/ocr_recognition.test.py
"""
from __future__ import annotations
import sys, os, time, traceback, json
from playwright.sync_api import sync_playwright, Page

ROOT = "http://127.0.0.1:8766/index.html"
FAIL = []
PASS = []

def fail(name, msg):
    FAIL.append((name, msg))
    print(f"[FAIL] {name}: {msg}")

def ok(name):
    PASS.append(name)
    print(f"[PASS] {name}")

def reload(page: Page, wait_ms=2600):
    page.goto(ROOT, wait_until="networkidle")
    page.wait_for_timeout(wait_ms)
    try:
        page.wait_for_function("typeof DB !== 'undefined' && DB && DB.db", timeout=15000)
    except Exception:
        pass
    # 确保 parseOCRResult 存在
    page.wait_for_function("typeof parseOCRResult === 'function'", timeout=10000)
    # 模拟一次用户手势（部分页面有交互守卫）
    page.evaluate("""(function(){
        try{
            const evt = new MouseEvent('click', {bubbles:true, cancelable:true, view:window});
            (document.body || document.documentElement).dispatchEvent(evt);
        }catch(_){}
    })();""")
    page.wait_for_timeout(200)

# ---------- 辅助：在页面上下文调用 parseOCRResult ----------
def parse_text(page, text, extra_rules=None):
    return page.evaluate("""([t, er]) => parseOCRResult(t, er || [])""", [text, extra_rules or []])

# ---------- 断言辅助 ----------
def assert_eq(actual, expected, case, field):
    if actual != expected:
        fail(case, f"{field} 期望 {expected!r}，实际 {actual!r}")
        return False
    return True

def assert_contains(container, item, case, desc):
    if item not in container:
        fail(case, f"{desc}: {item!r} 不在实际值 {container!r} 中")
        return False
    return True

# =========================================================
# O1：标准处方 —— 药名前缀 + Qd + 具体时间 + 起始日期
# =========================================================
def test_O1(page: Page):
    case = "O1"
    text = (
        "药品名称：阿莫西林胶囊\n"
        "规格：0.25g*24粒\n"
        "用法用量：口服 每次 2 粒 每日一次 08:30\n"
        "开始日期：2025-09-01"
    )
    r = parse_text(page, text)
    ok_count = 0
    if assert_eq(bool(r.get('name')), True, case, 'name 非空'):
        if assert_contains(r['name'], '阿莫西林', case, 'name 含「阿莫西林」'):
            ok_count += 1
    if assert_eq(r.get('freq'), 'daily', case, 'freq'): ok_count += 1
    dts = r.get('defaultTimes') or []
    if '08:30' in dts: ok_count += 1
    else: fail(case, f"defaultTimes 应含 08:30，实际 {dts!r}")
    if assert_eq(r.get('startDate'), '2025-09-01', case, 'startDate'): ok_count += 1
    dose = r.get('dose') or ''
    if '2' in dose and ('粒' in dose or 'mg' in dose or 'g' in dose): ok_count += 1
    else: fail(case, f"dose 应含「X 粒/克」，实际 {dose!r}")
    if ok_count >= 5: ok(case)

# =========================================================
# O2：Bid 早晚两次
# =========================================================
def test_O2(page: Page):
    case = "O2"
    text = (
        "【通用名】硝苯地平缓释片\n"
        "口服：每日两次，早晚各一次，每次 1 片(10mg)\n"
        "饭后服用"
    )
    r = parse_text(page, text)
    ok_count = 0
    if assert_eq(r.get('freq'), 'twice', case, 'freq=twice'): ok_count += 1
    dts = r.get('defaultTimes') or []
    # Bid 默认应是两槽（08:00 20:00）
    if len(dts) == 2: ok_count += 1
    else: fail(case, f"defaultTimes 长度应为 2，实际 {len(dts)} {dts!r}")
    if '08:00' in dts and '20:00' in dts: ok_count += 1
    else: fail(case, f"defaultTimes 应含 08:00/20:00，实际 {dts!r}")
    name = r.get('name') or ''
    if '硝苯地平' in name: ok_count += 1
    else: fail(case, f"name 应含「硝苯地平」，实际 {name!r}")
    dose = r.get('dose') or ''
    if '1' in dose and '片' in dose: ok_count += 1
    else: fail(case, f"dose 应含「1 片」，实际 {dose!r}")
    if ok_count >= 5: ok(case)

# =========================================================
# O3：Tid 三餐后
# =========================================================
def test_O3(page: Page):
    case = "O3"
    text = (
        "药名：头孢克肟分散片\n"
        "剂量：每次 100mg (1片)\n"
        "每日三次 三餐后服用\n"
        "起始日期 2025年10月15日"
    )
    r = parse_text(page, text)
    ok_count = 0
    if assert_eq(r.get('freq'), 'thrice', case, 'freq=thrice'): ok_count += 1
    dts = r.get('defaultTimes') or []
    if len(dts) == 3: ok_count += 1
    else: fail(case, f"defaultTimes 长度应为 3，实际 {len(dts)} {dts!r}")
    if '头孢克肟' in (r.get('name') or ''): ok_count += 1
    else: fail(case, f"name 应含「头孢克肟」，实际 {r.get('name')!r}")
    if '100mg' in (r.get('dose') or ''): ok_count += 1
    else: fail(case, f"dose 应含 100mg，实际 {r.get('dose')!r}")
    if assert_eq(r.get('startDate'), '2025-10-15', case, 'startDate=2025-10-15'): ok_count += 1
    if ok_count >= 5: ok(case)

# =========================================================
# O4：纯 3 个 HH:MM 无频次词 → 自动升级为 thrice
# =========================================================
def test_O4(page: Page):
    case = "O4"
    text = (
        "药品名称：布洛芬缓释胶囊\n"
        "每次 0.3g (1 粒)\n"
        "服用时间 07:45 12:30 19:10"
    )
    r = parse_text(page, text)
    ok_count = 0
    if assert_eq(r.get('freq'), 'thrice', case, '应根据 3 条时间自动升级为 thrice'): ok_count += 1
    dts = r.get('defaultTimes') or []
    if len(dts) == 3: ok_count += 1
    else: fail(case, f"defaultTimes 长度应为 3，实际 {len(dts)} {dts!r}")
    # times 字段（原始命中值）应含这三个时间
    times_raw = r.get('times') or []
    for t in ['07:45', '12:30', '19:10']:
        if t in times_raw: ok_count += 0.5
        else: fail(case, f"times 应包含 {t}，实际 {times_raw!r}")
    name = r.get('name') or ''
    if '布洛芬' in name: ok_count += 1
    else: fail(case, f"name 应含「布洛芬」，实际 {name!r}")
    if ok_count >= 4.5: ok(case)

# =========================================================
# O5：睡前一次（f_bedtime 优先级 12 高于 f_qd 的 9，应默认 22:00）
# =========================================================
def test_O5(page: Page):
    case = "O5"
    text = "药物名称：艾司唑仑片\n用量：每次 1 mg\n每日一次 睡前服用"
    r = parse_text(page, text)
    ok_count = 0
    # 注意：f_bedtime targetFreq = daily，但默认时间是 22:00
    if assert_eq(r.get('freq'), 'daily', case, 'freq=daily（睡前归类为每日一次）'): ok_count += 1
    dts = r.get('defaultTimes') or []
    if '22:00' in dts: ok_count += 1
    else: fail(case, f"睡前服用应默认 22:00，实际 defaultTimes={dts!r}")
    # times 命中词里也应含"睡前"映射的 22:00
    times_raw = r.get('times') or []
    if '22:00' in times_raw: ok_count += 0.5
    if '艾司唑仑' in (r.get('name') or ''): ok_count += 1
    else: fail(case, f"name 应含「艾司唑仑」，实际 {r.get('name')!r}")
    if '1' in (r.get('dose') or '') and 'mg' in (r.get('dose') or ''): ok_count += 1
    else: fail(case, f"dose 应含 1 mg，实际 {r.get('dose')!r}")
    if ok_count >= 4: ok(case)

# =========================================================
# O6：每周一、三、五 → weekly + weekdays=[1,3,5]
# =========================================================
def test_O6(page: Page):
    case = "O6"
    text = (
        "药名：甲氨蝶呤片\n"
        "每次 2.5mg (1 片)\n"
        "每周一次，每周一、三、五 早晨 8 点服用\n"
        "2025.08.28 开始"
    )
    r = parse_text(page, text)
    ok_count = 0
    if assert_eq(r.get('freq'), 'weekly', case, 'freq=weekly'): ok_count += 1
    wd = r.get('weekdays') or []
    if 1 in wd and 3 in wd and 5 in wd: ok_count += 1
    else: fail(case, f"weekdays 应含 [1,3,5]，实际 {wd!r}")
    dts = r.get('defaultTimes') or []
    if '08:00' in dts: ok_count += 0.5
    else: fail(case, f"defaultTimes 应含 08:00，实际 {dts!r}")
    if '甲氨蝶呤' in (r.get('name') or ''): ok_count += 1
    else: fail(case, f"name 应含「甲氨蝶呤」，实际 {r.get('name')!r}")
    if '2.5mg' in (r.get('dose') or ''): ok_count += 1
    else: fail(case, f"dose 应含 2.5mg，实际 {r.get('dose')!r}")
    if assert_eq(r.get('startDate'), '2025-08-28', case, 'startDate=2025-08-28'): ok_count += 1
    if ok_count >= 5.5: ok(case)

# =========================================================
# O7：隔天一次 → everyother
# =========================================================
def test_O7(page: Page):
    case = "O7"
    text = (
        "药品名称：阿司匹林肠溶片\n"
        "规格：100mg\n"
        "用法：口服 每次 1 片 隔天一次 早饭后"
    )
    r = parse_text(page, text)
    ok_count = 0
    if assert_eq(r.get('freq'), 'everyother', case, 'freq=everyother'): ok_count += 1
    if '阿司匹林' in (r.get('name') or ''): ok_count += 1
    else: fail(case, f"name 应含「阿司匹林」，实际 {r.get('name')!r}")
    dts = r.get('defaultTimes') or []
    # 早饭后 → 08:00
    if '08:00' in dts: ok_count += 1
    else: fail(case, f"defaultTimes 应含 08:00，实际 {dts!r}")
    dose = r.get('dose') or ''
    if '100mg' in dose or ('1' in dose and '片' in dose): ok_count += 1
    else: fail(case, f"dose 应含「100mg 或 1片」，实际 {dose!r}")
    if ok_count >= 4: ok(case)

# =========================================================
# O8：三层规则优先级（用户 +100 > 管理员 +50 > 内置 0）
#     用户规则把 "神奇颗粒XYZ" 识别为 name
#     管理员规则把 "神奇颗粒XYZ" 识别为 dose
#     最终 name 应是用户规则命中值
# =========================================================
def test_O8(page: Page):
    case = "O8"
    user_rules = [{
        "id": "u1", "field": "name", "priority": 10, "__layer": "user",  # 合并优先级最高
        "regex": "(神奇颗粒[A-Za-z]{1,10})"
    }]
    admin_rules = [{
        "id": "a1", "field": "dose", "priority": 10, "__layer": "admin",  # 管理员层：内置已覆盖 dose 就不抢
        "regex": "(神奇颗粒[A-Za-z]{1,10})"
    }]
    # 额外规则顺序：用户 + 管理员 → 合并到 extraRules
    extra = user_rules + admin_rules
    text = (
        "用法说明：饭后服用\n"
        "神奇颗粒XYZ 每日一次 每次 1 袋 08:00"
    )
    r = parse_text(page, text, extra)
    ok_count = 0
    name = r.get('name') or ''
    if '神奇颗粒XYZ' in name: ok_count += 1
    else: fail(case, f"用户规则优先级更高，name 应含「神奇颗粒XYZ」，实际 name={name!r}")
    # freq 仍应由内置 Qd 关键词命中 → daily
    if assert_eq(r.get('freq'), 'daily', case, 'freq=daily'): ok_count += 1
    dts = r.get('defaultTimes') or []
    if '08:00' in dts: ok_count += 0.5
    dose = r.get('dose') or ''
    if '1' in dose and '袋' in dose: ok_count += 1
    else: fail(case, f"dose 应含「1 袋」，实际 {dose!r}")
    if ok_count >= 3: ok(case)


# =========================================================
# main
# =========================================================
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 820},
            locale="zh-CN",
        )
        page = ctx.new_page()
        # 把所有 console.error/warn 抓出来便于调试
        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text[:400]}"))
        try:
            reload(page)
        except Exception as e:
            print(f"[ERROR] 页面加载失败: {e}")
            traceback.print_exc()
            browser.close()
            sys.exit(2)

        tests = [
            ("O1", test_O1),
            ("O2", test_O2),
            ("O3", test_O3),
            ("O4", test_O4),
            ("O5", test_O5),
            ("O6", test_O6),
            ("O7", test_O7),
            ("O8", test_O8),
        ]

        # 单独捕获每个测试的异常
        for name, fn in tests:
            try:
                fn(page)
            except Exception as e:
                fail(name, f"抛出异常：{e}")
                traceback.print_exc()

        browser.close()

    total = len(tests)
    passed = len(PASS)
    failed = len(FAIL)
    print("\n" + "=" * 60)
    print(f"OCR 解析 TDD 总计: {total}  通过: {passed}  失败: {failed}")
    print("=" * 60)
    if FAIL:
        print("失败明细:")
        for n, m in FAIL:
            print(f"  - {n}: {m}")
        sys.exit(1)
    else:
        print("全部通过 ✓")
        sys.exit(0)

if __name__ == "__main__":
    main()

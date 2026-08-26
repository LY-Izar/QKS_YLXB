"""
TDD: 邮箱绑定持久化测试
- RED:  编写测试，验证 init() 云端探针拉取 email / email_remind 并回填本地
- GREEN: 修改 index.html，让 init() 在登录态探针中拉取并回写邮箱字段
"""
import pathlib, re
ROOT = pathlib.Path(r'c:\Users\Administrator\Desktop\医路相伴')
html = (ROOT/'index.html').read_text(encoding='utf-8')
fail=0;pass_=0
def t(n,c):
    global fail,pass_
    if c: print('  OK  ',n); pass_+=1
    else: print('  FAIL',n); fail+=1

print('TDD: 邮箱绑定后刷新仍持久化（云端探针补全 email 字段）')
print()

# Test 1: init() 云端探针 select= 必须包含 email 和 email_remind
# 探针是在 init() 里的 sbFetch('users?limit=1&select=id,is_admin,role,family_code...
probe_match = re.search(r"sbFetch\s*\(\s*['\"]users\?limit=1&select=([^'\"]+)['\"]", html)
probe_select = probe_match.group(1) if probe_match else ''
t('T1 init 云端探针 select 列表包含 email', bool(re.search(r'\bemail\b', probe_select)))
t('T2 init 云端探针 select 列表包含 email_remind', bool(re.search(r'email_remind', probe_select)))

# Test 3: 探针返回的 rows[0].email 会同步回本地 DB
t('T3 init 探针成功后，把云端 email 写回 IndexedDB',
  bool(re.search(r"rows\[0\]\.email", html)) and
  bool(re.search(r"email.*DB\.put\('users'|DB\.put\('users'.*email", html, re.S)))

# Test 4: doBindEmail 已在 PATCH 云端 email（验证原逻辑仍在）
bind_block_match = re.search(
    r"async function doBindEmail\(\)\{[\s\S]*?\n\}",
    html)
bind_block = bind_block_match.group(0) if bind_block_match else ''
t('T4 doBindEmail 对云端 PATCH email',
  bool(re.search(r"method\s*:\s*'PATCH'", bind_block)) and
  bool(re.search(r"JSON\.stringify\(\{email", bind_block)))

# Test 5: init 探针失败时（降级列不存在）仍会继续其他逻辑
# 即 select 包含 email,email_remind 后，如果 400，降级查询需保持流程继续
init_match = re.search(
    r"async function init\(\)\{[\s\S]*?if\(currentUser\)\{[\s\S]*?if\(cloudUsable\(\)\)\{[\s\S]*?try\{([\s\S]*?)\}catch",
    html)
init_block = init_match.group(1) if init_match else ''
t('T5 当 email/email_remind 列不存在导致 400 时，init 探针有降级兜底',
  ('email,email_remind' in init_block) and
  ("status === 400" in init_block) and
  ("sbFetch('users?limit=1&select=id,is_admin,role,family_code" in init_block))

# Test 6: init 探针成功后把回写逻辑用 DB.put 保证 email 回填
# 具体要有 "lr.email = real[0].email" 或类似赋值
t('T6 init 探针成功时，把云端 email 赋值给本地 rec',
  bool(re.search(r"lr\.email\s*=|localRec\.email\s*=|email\s*:\s*real\[0\]", html)))

print()
print(f'Result: PASS {pass_}/{pass_+fail}; FAIL {fail}')
import sys; sys.exit(1 if fail > 0 else 0)

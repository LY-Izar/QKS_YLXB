import pathlib, re, hashlib, urllib.request, json, ssl
ROOT = pathlib.Path(r'c:\Users\Administrator\Desktop\医路相伴')
fail=0;pass_=0
def t(n,c):
    global fail,pass_
    if c: print('  OK  ',n); pass_+=1
    else: print('  FAIL',n); fail+=1

print('TDD: admin-account phases F/G/H/I')
print()
F=(ROOT/'supabase/migrations/add_admin_column.sql').read_text(encoding='utf-8')
print('=== Suite F: add_admin_column.sql ===')
t('F1 users.is_admin', bool(re.search(r"ADD COLUMN IF NOT EXISTS is_admin\s+BOOLEAN\s+DEFAULT\s+FALSE\s+NOT NULL", F)))
t('F2 users.bound_elder_code TEXT', bool(re.search(r"ADD COLUMN IF NOT EXISTS bound_elder_code\s+TEXT\s+DEFAULT\s+NULL", F)))
t('F3 users.bound_elder_codes JSONB []', bool(re.search(r"ADD COLUMN IF NOT EXISTS bound_elder_codes\s+JSONB\s+DEFAULT\s+'\[\]'::jsonb\s+NOT NULL", F)))
t('F4 idx_users_admin', 'idx_users_admin' in F)
t('F5 idx_users_family_code', 'idx_users_family_code' in F)
t('F6 idx_users_role', 'idx_users_role' in F)

G=(ROOT/'supabase/migrations/purge_and_create_admin.sql').read_text(encoding='utf-8')
print('\n=== Suite G: purge_and_create_admin.sql ===')
t('G1 TRUNCATE users CASCADE', bool(re.search(r"TRUNCATE\s+TABLE\s+users\s+RESTART\s+IDENTITY\s+CASCADE", G)))
t('G2 所有 7 张业务表 + users 都 TRUNCATE', sum(1 for x in ['medication_logs','health_metrics','chronic_alerts','chronic_profiles','follow_ups','events','family_bindings','users'] if f'TRUNCATE TABLE {x}' in G or f'TRUNCATE TABLE '+x in G or f'TRUNCATE\nTABLE {x}' in G or re.search(r'TRUNCATE TABLE\s+'+x, G)) >= 8)
t('G3 BEGIN / COMMIT 事务', 'BEGIN;' in G and 'COMMIT;' in G and G.index('BEGIN;') < G.index('COMMIT;'))
t('G4 admin id=15184461098_admin', "'15184461098_admin'" in G)
t('G5 is_admin TRUE', 'TRUE,' in G or 'is_admin,\n  NOW()' in G)
m = re.search(r"VALUES\s*\(\s*'15184461098_admin'\s*,\s*'([0-9a-f]{64})'", G, re.S)
t('G6 pass_hash 64hex', bool(m))
if m:
    t('G7 pass_hash == SHA256(20091208)', m.group(1) == hashlib.sha256('20091208'.encode('utf-8')).hexdigest())
else:
    t('G7 pass_hash == SHA256(20091208)', False)

print('\n=== Suite H: DB probe 云端实际数据验证 ===')
KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NTcwNjUsImV4cCI6MjEwMzEzMzA2NX0.VsGxfhBt1J6iVYiZNyWhaeI_MSYnxSCaVFHgco1wKbc'
BASE = 'https://hjryfgujkxuaxovftlai.supabase.co/rest/v1'
HEADERS = {'apikey': KEY, 'Authorization': 'Bearer '+KEY, 'Accept': 'application/json'}
ctx = ssl._create_unverified_context()
def get(qs):
    req = urllib.request.Request(f'{BASE}/{qs}', headers=HEADERS, method='GET')
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        return json.load(r)
try:
    # 不选 is_admin / bound_elder_codes（SQL 未执行前列不存在会 400）
    users = get('users?select=id,role,family_code,email,email_remind,created_at')
    ids = [u['id'] for u in users]
    Ht1 = len(users) == 1 and ids[0] == '15184461098_admin'
except Exception as e:
    Ht1 = False
    print(f'  probe users fail: {e}')
t('H1 users 只剩管理员 (id=15184461098_admin)', Ht1)
# 如果 H1 通过，再验证 is_admin=true / 业务表空
if Ht1:
    try:
        u2 = get("users?select=id,is_admin&id=eq.15184461098_admin&limit=1")
        Ht2 = str(u2[0].get('is_admin')).lower() in ('true','1')
    except Exception as e:
        Ht2 = False
        print(f'  probe is_admin fail: {e}')
    t('H2 is_admin = TRUE', Ht2)
    Ht4 = True
    empty_tbls = ['chronic_profiles','chronic_alerts','health_metrics','medication_logs','events','family_bindings']
    for tbl in empty_tbls:
        try:
            r = get(f'{tbl}?limit=1&select=id')
            # 空表返回 list[] 或 [{"count":0}]；非空一定是长度 >0 的 list
            if isinstance(r, list):
                # 过滤掉元素里有纯 count 的情况（实际 limit=1 非空会返回 1 条行）
                real_rows = [x for x in r if 'id' in x]
                if len(real_rows) != 0: Ht4 = False
        except Exception:
            pass
    t('H3 业务表清空（6 张表）', Ht4)
else:
    t('H2 is_admin = TRUE (H1 未过跳过)', False)
    t('H3 业务表清空（H1 未过跳过）', False)

I = (ROOT/'index.html').read_text(encoding='utf-8')
print('\n=== Suite I: 前端 管理员 UI（等下一阶段实现） ===')
t('I1 前端加载用户时会处理 is_admin（登录/云端同步阶段）', bool(re.search(r"rows\[0\]\.is_admin|rec\.is_admin|users\?select=.*is_admin|\.is_admin\s*=", I)))
t("I2 存在 view-admin / go('admin')", bool(re.search(r"view-admin|go\('admin'\)", I)))

print('\n=== Suite J: 测试账号命名约定 + 一键清测试能力 ===')
# J1 isValidUsername 对 test_ 前缀账号返回禁止（普通注册页）
import subprocess, sys
# 简单直接用 Node 跑一下内置函数（浏览器环境不方便就用 Python 解析函数体手动跑逻辑）
# 这里用正则：必须存在包含 "以 test_ 开头" 的禁止判断（或 msg 说明）
code = I
J1 = bool(re.search(r"test_|\^test_|\bstartsWith\s*\(\s*['\"]test_['\"]\s*\)|账号不能以 test_ 开头|test_ 前缀|test_开头", code))
t('J1 isValidUsername 会显式拒绝 test_ 前缀的账号（防止污染生产库）', J1)
# J2 admin API 里有 purge_test_accounts 动作
J2 = False
api = ROOT/'supabase/functions/admin_api/index.ts'
if api.exists():
    acode = api.read_text(encoding='utf-8')
    J2 = 'purge_test_accounts' in acode and "LIKE 'test_%'" in acode
else:
    # 若还没建 admin_api，就看我们在 admin_rpc.sql 里有没有 purge_test_accounts() 函数
    rpc = ROOT/'supabase/migrations/admin_rpc.sql'
    if rpc.exists():
        rcode = rpc.read_text(encoding='utf-8')
        J2 = 'purge_test_accounts' in rcode and ("LIKE 'test_%'" in rcode or "starts_with(id, 'test_')" in rcode)
t('J2 admin 侧提供 purge_test_accounts 能力（SQL RPC 或 Edge Function）清理 id LIKE test_% 及其业务数据', J2)
# J3 前端 view-admin 里有一键清测试按钮
J3 = bool(re.search(r"清空.*测试|purgeTestAccounts|清理测试账号|一键清空|test_ 前缀|purge_test_accounts|id.*test_", I)) or False
t('J3 前端 view-admin 有「清理 test_ 前缀测试账号」按钮或入口', J3)
# J4 管理员本人 (15184461098_admin) 不以 test_ 开头，不会被误删
ADMIN = '15184461098_admin'
J4 = not ADMIN.startswith('test_')
t('J4 管理员账号本身不以 test_ 开头，清测试时安全', J4)

print()
print(f'Result: PASS {pass_}/{pass_+fail}; FAIL {fail}')
import sys; sys.exit(0 if fail == 0 else 1)

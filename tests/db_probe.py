import hashlib, json, urllib.request, urllib.parse, ssl
KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NTcwNjUsImV4cCI6MjEwMzEzMzA2NX0.VsGxfhBt1J6iVYiZNyWhaeI_MSYnxSCaVFHgco1wKbc'
BASE = 'https://hjryfgujkxuaxovftlai.supabase.co/rest/v1'
HEADERS = {'apikey': KEY, 'Authorization': 'Bearer '+KEY, 'Accept': 'application/json'}
# 先探测有哪些表
tables = ['users','chronic_profiles','chronic_alerts','health_metrics','medication_logs','events','follow_ups','family_bindings']
ctx = ssl._create_unverified_context()
print('=== 数据库现状探测 ===')
for t in tables:
    try:
        req = urllib.request.Request(f'{BASE}/{t}?limit=10000', headers=HEADERS, method='GET')
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            data = json.load(r)
            cols = sorted(list(data[0].keys())) if data else []
            print(f'TABLE {t:25s} rows={len(data):6d}  sample_cols={cols[:15]}')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8','ignore')[:200]
        print(f'TABLE {t:25s} HTTP {e.code}: {body}')
    except Exception as e:
        print(f'TABLE {t:25s} ERR: {e}')
# 打印 users 表实际 id 列表
print('\n=== users 表所有 id ===')
try:
    req = urllib.request.Request(f'{BASE}/users?select=id,role,email,email_remind,created_at&order=created_at.asc.nullslast', headers=HEADERS, method='GET')
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        us = json.load(r)
        print(json.dumps(us, ensure_ascii=False, indent=2))
except Exception as e:
    print('ERR', e)

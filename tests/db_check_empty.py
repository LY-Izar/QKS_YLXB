import urllib.request, json, ssl
KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NTcwNjUsImV4cCI6MjEwMzEzMzA2NX0.VsGxfhBt1J6iVYiZNyWhaeI_MSYnxSCaVFHgco1wKbc'
BASE='https://hjryfgujkxuaxovftlai.supabase.co/rest/v1'
H={'apikey':KEY,'Authorization':'Bearer '+KEY,'Accept':'application/json'}
ctx=ssl._create_unverified_context()
for t in ['chronic_profiles','chronic_alerts','health_metrics','medication_logs','events','family_bindings','follow_ups']:
    for qs in [f'{t}?select=count&limit=1000000', f'{t}?limit=1&select=*']:
        try:
            req=urllib.request.Request(f'{BASE}/{qs}',headers=H,method='GET')
            with urllib.request.urlopen(req,context=ctx,timeout=15) as r:
                body=r.read().decode('utf-8','ignore')
                print(t, '→', qs.split('?')[1], 'STATUS', r.status, 'BODY', body[:200])
        except urllib.error.HTTPError as e:
            b=e.read().decode('utf-8','ignore')[:300]
            print(t,'→',qs.split('?')[1],'HTTP',e.code,b)
        except Exception as e:
            print(t,'ERR',e)
    print()

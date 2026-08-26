"""Clean up orphan events (events whose family_code doesn't exist in users table)."""
import requests, json

SB_URL = 'https://hjryfgujkxuaxovftlai.supabase.co/rest/v1'
SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NTcwNjUsImV4cCI6MjEwMzEzMzA2NX0.VsGxfhBt1J6iVYiZNyWhaeI_MSYnxSCaVFHgco1wKbc'
headers = {'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY}

# Get all events
r = requests.get(f'{SB_URL}/events?select=id,family_code', headers=headers)
if not r.ok:
    print(f'Error fetching events: {r.status_code} - {r.text[:300]}')
    exit(1)

events = r.json()
print(f'Events before cleanup: {len(events)}')
for e in events:
    print(f'  id={e["id"]}, family_code={e["family_code"]}')

# Get all valid family_codes from users
r2 = requests.get(f'{SB_URL}/users?select=family_code&family_code=not.is.null', headers=headers)
if not r2.ok:
    print(f'Error fetching users: {r2.status_code}')
    exit(1)

valid_codes = [u['family_code'] for u in r2.json() if u.get('family_code')]
print(f'\nValid family codes in users table: {valid_codes}')

# Delete orphan events
deleted = 0
for event in events:
    fc = event['family_code']
    if fc and fc not in valid_codes:
        print(f'\nDeleting orphan event id={event["id"]} (family_code="{fc}" not in users)')
        d = requests.delete(f'{SB_URL}/events?id=eq.{event["id"]}', headers=headers)
        print(f'  DELETE result: {d.status_code}')
        if d.ok:
            deleted += 1

# Verify
r3 = requests.get(f'{SB_URL}/events?select=id,family_code&limit=5', headers=headers)
final = r3.json() if r3.ok else []
print(f'\nAfter cleanup: {len(final)} events remaining (deleted {deleted} orphans)')
for e in final:
    print(f'  id={e["id"]}, family_code={e["family_code"]}')

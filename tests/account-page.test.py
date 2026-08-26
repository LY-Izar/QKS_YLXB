import sys, re, pathlib
p = pathlib.Path(r'c:\Users\Administrator\Desktop\医路相伴\index.html')
html = p.read_text(encoding='utf-8')
fail=0;pass_=0
def t(name,cond):
    global fail,pass_
    if cond:
        print(f'  OK   {name}'); pass_+=1
    else:
        print(f'  FAIL {name}'); fail+=1
print('TDD: account-page tests RED')
print()
print('=== Suite A ===')
t('A1 view-account div exists', bool(re.search(r'id="view-account"', html)))
t('A2 nav has go account entry', bool(re.search(r"go\('account'\)", html)))
t('A3 async function go(view) exists', bool(re.search(r'async function go\(view\)', html)))
t('A4 speakCurrent map has view-account', "'view-account'" in html)
print()
print('=== Suite B ===')
m = re.search(r'<div class="view" id="view-account">.*?(?=<div class="view" id="|</main>)', html, re.S)
va = m.group(0) if m else ''
t('B1 view-account contains accountSection wrapper', 'id="accountSection"' in va)
t('B2 change-username button in view-account', '修改用户名' in va)
t('B3 change-password button in view-account', '修改密码' in va)
t('B4 email-bind + currentEmailHint in view-account', '邮箱绑定' in va and 'id="currentEmailHint"' in va)
t('B5 bound-elder list + viewElder in view-account', '查看已绑定老人' in va and 'id="boundElderList"' in va)
print()
print('=== Suite C ===')
mh = re.search(r'<div class="view" id="view-home">.*?(?=<div class="view" id="|</main>)', html, re.S)
vh = mh.group(0) if mh else ''
t('C1 home-view NO id=accountSection (big card removed)', 'id="accountSection"' not in vh)
t("C2 home-view has entry to account (btn or link)", bool(re.search(r"go\('account'\)", vh)) or '账户设置' in vh)
print()
print('=== Suite D ===')
ul_m = re.search(r'<ul class="nav-links".*?</ul>', html, re.S)
ul = ul_m.group(0) if ul_m else ''
t('D1 nav has data-v="account"', bool(re.search(r'data-v="account"', ul)))
t('D2 nav account item onclick go(account)', bool(re.search(r'data-v="account".*?go\(\'account\'\)', ul, re.S)))
t('D3 nav .nav-link no data-v="welcome"', not re.search(r'class="nav-link"\s+data-v="welcome"', ul))
print()
print('=== Suite E ===')
t('E1 renderAccountSection function exists', bool(re.search(r'function renderAccountSection\(\)', html)))
go_m = re.search(r'async function go\(view\)\{.*?(?=\n/\*|\nfunction |\nconst |\nclass |\Z)', html, re.S)
gob = go_m.group(0) if go_m else ''
t('E2 go body handles view===account branch', bool(re.search(r"view\s*===\s*'account'", gob)))
print()
print(f'Result: PASS {pass_}/{pass_+fail}; FAIL {fail}')
sys.exit(1 if fail else 0)

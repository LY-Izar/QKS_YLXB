$ErrorActionPreference='Stop'
$fail=0;$pass=0;
function Test-It($name,$cond){ if($cond){ Write-Host ('  OK '+$name) -ForegroundColor Green; $script:pass++ } else { Write-Host ('  FAIL '+$name) -ForegroundColor Red; $script:fail++ } }
$localHtml=[System.IO.File]::ReadAllText('c:\Users\Administrator\Desktop\医路相伴\index.html',[Text.Encoding]::UTF8)
Write-Host 'TDD: account-page tests (RED phase first)'
Write-Host ''
Write-Host '=== Suite A: view ==='
Test-It 'A1 view-account div exists' ($localHtml -match 'id="view-account"')
Test-It 'A2 nav has go account entry' ($localHtml -match "go\(\x27account\x27\)")
Test-It 'A3 async function go(view) exists' ($localHtml -match 'async function go\(view\)')
Test-It 'A4 speakCurrent has view-account entry' ($localHtml -match [regex]::Escape("'view-account'"))

Write-Host ''
Write-Host '=== Suite B: accountSection inside view-account ==='
$va=[regex]::Match($localHtml,'(?s)<div class="view" id="view-account">.*?(</div>\s*</div>\s*<div class="view|<div class="view" id="view-|</main>)').Value
Test-It 'B1 view-account contains accountSection wrapper' ($va -match 'id="accountSection"')
Test-It 'B2 contains change-username button' ($va -match '修改用户名')
Test-It 'B3 contains change-password button' ($va -match '修改密码')
Test-It 'B4 contains email-bind + currentEmailHint' (($va -match '邮箱绑定') -and ($va -match 'id="currentEmailHint"'))
Test-It 'B5 contains bound-elder list + viewElder' (($va -match '查看已绑定老人') -and ($va -match 'id="boundElderList"'))

Write-Host ''
Write-Host '=== Suite C: home-view no more big account card ==='
$vh=[regex]::Match($localHtml,'(?s)<div class="view" id="view-home">.*?(?=<div class="view" id=")').Value
Test-It 'C1 home does NOT contain id=accountSection' (-not ($vh -match 'id="accountSection"'))
Test-It 'C2 home has jump button to account' (($vh -match "go\(\x27account\x27\)") -or ($vh -match '账户设置'))

Write-Host ''
Write-Host '=== Suite D: nav ==='
$ul=[regex]::Match($localHtml,'(?s)<ul class="nav-links".*?</ul>').Value
Test-It 'D1 nav has data-v=account' ($ul -match 'data-v="account"')
Test-It 'D2 nav account item onclick calls go(account)' ($ul -match 'data-v="account".*?go\(\x27account\x27\)')
Test-It 'D3 nav-link does not use data-v=welcome any more' (-not ($ul -match 'class="nav-link"\s+data-v="welcome"'))

Write-Host ''
Write-Host '=== Suite E: renderAccountSection ==='
Test-It 'E1 function renderAccountSection exists' ($localHtml -match 'function renderAccountSection\(\)')
$goBody=[regex]::Match($localHtml,'(?s)async function go\(view\)\{.*?^\s*\}').Value
Test-It 'E2 go(account) branch calls renderAccountSection' ($goBody -match "view\s*===\s*\x27account\x27")

Write-Host ''
Write-Host ('Result: PASS '+$pass+' / '+($pass+$fail)+' FAIL '+$fail)
if($fail -gt 0){ exit 1 }
Write-Host 'ALL GREEN' -ForegroundColor Green
exit 0

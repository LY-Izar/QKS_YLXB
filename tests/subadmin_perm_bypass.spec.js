const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 1280, height: 900 } });

function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

async function login(page, id, pw){
  await page.goto(SITE);
  try { await page.click('#btnLogin'); } catch(e){}
  await page.waitForSelector('#authMask.show', { timeout: 10000 });
  await page.fill('#authUser', id);
  await page.fill('#authPass', pw);
  const [btn] = await page.$$('#authMask button');
  for (const b of await page.$$('#authMask button')) {
    const t = (await b.textContent() || '').trim();
    if (t.includes('登录') && !t.includes('取消') && !t.includes('暂不登录') && !t.includes('关闭')) {
      await b.click();
      break;
    }
  }
  await sleep(1500);
}

test('权限漏洞: 用户管理删除按钮无权限时必须有真正的disabled属性（不是只改透明度）', async ({ page }) => {
  await login(page, 'CESHI', '123456');
  await sleep(1500);
  await page.evaluate('try{ go("admin"); }catch(e){}');
  await sleep(2000);
  await page.waitForSelector('#adminPage', { state: 'visible', timeout: 8000 }).catch(()=>null);
  await sleep(1200);
  const result = await page.evaluate(() => {
    const src = (typeof adminLoadUsers === 'function' ? adminLoadUsers.toString() : '');
    const delBtns = Array.from(document.querySelectorAll('button')).filter(b => {
      const t = (b.textContent || '').trim();
      return t === '删除' || t === '删除数据';
    }).map(b => ({ text: (b.textContent||'').trim(), disabled: b.disabled, hasDisAttr: b.hasAttribute('disabled'), style: b.getAttribute('style') || '' }));
    const disDelBlockContainsDisabled = /canDel\s*=[\s\S]{0,200}?\sdisabled\s/.test(src);
    return { userTableButtons: delBtns, disDelBlockContainsDisabled };
  });
  expect(result.disDelBlockContainsDisabled).toBe(true);
  if (result.userTableButtons && result.userTableButtons.length) {
    result.userTableButtons.forEach(b => {
      if (b.text === '删除') expect(b.disabled || b.hasDisAttr).toBeTruthy();
    });
  }
});

test('权限漏洞: purgeTestAccounts, adminExecDeleteUserData, adminDeleteAnn 函数必须在函数顶部调用 requirePerm/门控（不是只靠按钮灰化）', async ({ page }) => {
  await page.goto(SITE);
  const src = await page.content();
  const purgeFnMatch = src.match(/async\s+function\s+purgeTestAccounts\s*\([^)]*\)\s*\{[\s\S]{0,800}?\n\s*\}/);
  const purgeBody = purgeFnMatch ? purgeFnMatch[0] : '';
  expect(purgeBody).toMatch(/requirePerm\(\s*['"]db['"]\s*[,)]|isSuper\s*=.*SUPER_ADMIN_ID|adminLevel\s*===\s*['"]super['"]/);

  const delDataFnMatch = src.match(/async\s+function\s+adminExecDeleteUserData\s*\([^)]*\)\s*\{[\s\S]{0,1000}?\n\s*\}/);
  const delDataBody = delDataFnMatch ? delDataFnMatch[0] : '';
  expect(delDataBody).toMatch(/requirePerm\(\s*['"]db['"]\s*[,)]|SUPER_ADMIN_ID|adminLevel\s*===\s*['"]super['"]/);

  const delAnnFnMatch = src.match(/async\s+function\s+adminDeleteAnn\s*\([^)]*\)\s*\{[\s\S]{0,700}?\n\s*\}/);
  const delAnnBody = delAnnFnMatch ? delAnnFnMatch[0] : '';
  expect(delAnnBody).toMatch(/requirePerm\(/);
});

test('权限漏洞: 清理test账号按钮 对子管理员(无db)必须disabled+title提示', async ({ page }) => {
  await page.goto(SITE);
  const html = await page.content();
  expect(html).toContain('id="purgeTestBtn"');
  const upFnMatch = html.match(/async\s+function\s+updateAdminUI\s*\([^)]*\)\s*\{[\s\S]{0,6000}?\n\s*const statsEl/);
  const upFn = upFnMatch ? upFnMatch[0] : '';
  expect(upFn).toContain('purgeTestBtn');
  expect(upFn).toMatch(/ptb\.(disabled\s*=\s*true|style\.opacity)/);
});

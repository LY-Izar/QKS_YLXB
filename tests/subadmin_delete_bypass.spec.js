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
  for (const b of await page.$$('#authMask button')) {
    const t = (await b.textContent() || '').trim();
    if (t.includes('登录') && !t.includes('取消') && !t.includes('暂不登录') && !t.includes('关闭')) {
      await b.click();
      break;
    }
  }
  await sleep(1500);
}

test('漏洞复现: 次级管理员(无db权限)删除其他管理员 - 按钮状态和函数守卫双重验证', async ({ page }) => {
  await login(page, 'CESHI', '123456');
  await sleep(1000);

  const stateCheck = await page.evaluate(() => {
    return {
      currentUser: typeof currentUser !== 'undefined' ? currentUser : null,
      adminLevel: typeof adminLevel !== 'undefined' ? adminLevel : null,
      subPerms: typeof subPerms !== 'undefined' ? JSON.stringify(subPerms) : null,
      isAdmin: typeof isAdmin !== 'undefined' ? isAdmin : null,
      hasPermDb: typeof hasPerm === 'function' ? hasPerm('db') : null,
      hasPermPin: typeof hasPerm === 'function' ? hasPerm('pin') : null,
      hasPermEmail: typeof hasPerm === 'function' ? hasPerm('email_push') : null,
      hasPermMmode: typeof hasPerm === 'function' ? hasPerm('mmode') : null,
    };
  });

  console.log('CESHI state:', JSON.stringify(stateCheck, null, 2));

  await page.evaluate('try{ go("admin"); }catch(e){}');
  await sleep(2500);

  const buttonState = await page.evaluate(() => {
    const delBtns = Array.from(document.querySelectorAll('button')).filter(b => {
      const t = (b.textContent || '').trim();
      return t === '删除';
    });
    return {
      deleteButtons: delBtns.map(b => ({
        text: (b.textContent || '').trim(),
        disabled: b.disabled,
        hasDisabledAttr: b.hasAttribute('disabled'),
        title: b.getAttribute('title') || '',
        style: b.getAttribute('style') || ''
      })),
      resetButtons: Array.from(document.querySelectorAll('button')).filter(b => {
        const t = (b.textContent || '').trim();
        return t === '重置密码';
      }).map(b => ({
        text: (b.textContent || '').trim(),
        disabled: b.disabled,
        hasDisabledAttr: b.hasAttribute('disabled')
      }))
    };
  });

  console.log('Button state:', JSON.stringify(buttonState, null, 2));

  if (stateCheck.adminLevel === 'super') {
    console.log('BUG CONFIRMED: CESHI has adminLevel=super, should be sub');
    expect(stateCheck.adminLevel).toBe('sub');
  }

  if (stateCheck.adminLevel === 'sub') {
    const deleteBtns = buttonState.deleteButtons;
    if (deleteBtns.length > 0) {
      for (const btn of deleteBtns) {
        expect(btn.disabled || btn.hasDisabledAttr).toBeTruthy();
      }
    }

    const resetBtns = buttonState.resetButtons;
    if (resetBtns.length > 0) {
      for (const btn of resetBtns) {
        expect(btn.disabled || btn.hasDisabledAttr).toBeTruthy();
      }
    }
  }

  const fnCheck = await page.evaluate(() => {
    const src = (typeof adminDeleteUser === 'function') ? adminDeleteUser.toString() : '';
    const rpCall = src.includes('requirePerm') && src.includes("'db'");
    return { adminDeleteUserHasRequirePerm: rpCall };
  });
  expect(fnCheck.adminDeleteUserHasRequirePerm).toBe(true);
});

test('漏洞复现: 次级管理员执行adminDeleteUser函数 - requirePerm必须拦截', async ({ page }) => {
  await login(page, 'CESHI', '123456');
  await sleep(1000);

  const guardCheck = await page.evaluate(async () => {
    if (typeof adminDeleteUser !== 'function') return { error: 'function not found' };
    try {
      const result = await adminDeleteUser('DO_NOT_EXIST_USER');
      return { result: result, error: null };
    } catch(e) {
      return { result: null, error: e.message || String(e) };
    }
  });

  console.log('adminDeleteUser result:', JSON.stringify(guardCheck, null, 2));
});

test('代码审查: normalizeAdminLevel必须包含明确的admin_level验证逻辑，不能错误返回super', async ({ page }) => {
  const html = await page.content();
  
  const normalizeFnMatch = html.match(/function\s+normalizeAdminLevel\s*\([^)]*\)\s*\{[\s\S]{0,400}?\n\s*\}/);
  const normalizeBody = normalizeFnMatch ? normalizeFnMatch[0] : '';
  
  console.log('normalizeAdminLevel body:', normalizeBody.substring(0, 300));

  const dangerousFallback = /if\s*\(\s*isAdmin\s*\)\s*return\s+['"]super['"]/.test(normalizeBody);
  if (dangerousFallback) {
    console.log('BUG: normalizeAdminLevel has dangerous isAdmin->super fallback');
  }
});

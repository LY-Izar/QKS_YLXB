const { test, expect } = require('@playwright/test');

const SITE = 'file:///C:/Users/Administrator/Desktop/%E5%8C%BB%E8%B7%AF%E7%9B%B8%E4%BC%B4/index.html';

test.use({ viewport: { width: 390, height: 844 } });

function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

test('BUG1: select语句包含admin_level和sub_perms字段', async ({ page }) => {
  await page.goto(SITE);
  const html = await page.content();
  const initMatch = html.match(/sbFetch\('users\?limit=1&select=[^']+' \+ encodeURIComponent\(currentUser\)\)/);
  const initStr = initMatch ? initMatch[0] : '';
  expect(initStr).toContain('admin_level');
  expect(initStr).toContain('sub_perms');
});

test('BUG1: 云探针后会调用 updateUserUI 刷新导航按钮', async ({ page }) => {
  await page.goto(SITE);
  const html = await page.content();
  expect(html).toMatch(/levelChanged \|\| permsChanged[\s\S]{0,200}updateUserUI\(\)/m);
});

test('BUG2: 登录模态框有取消/关闭按钮', async ({ page }) => {
  await page.goto(SITE);
  await page.click('#btnLogin');
  await sleep(300);
  const authMask = await page.$('#authMask.show');
  expect(authMask).not.toBeNull();
  const btnTexts = await page.$$eval('#authMask .btn', els => els.map(e => (e.textContent || '').trim()));
  const hasCancel = btnTexts.some(t => t.includes('取消') || t.includes('暂不登录') || t.includes('关闭'));
  expect(hasCancel).toBeTruthy();
  const buttons = await page.$$('#authMask .btn');
  let cancelBtn = null;
  for (const b of buttons) {
    const txt = await b.textContent();
    if (txt && (txt.includes('取消') || txt.includes('暂不登录') || txt.includes('关闭'))) { cancelBtn = b; break; }
  }
  expect(cancelBtn).not.toBeNull();
  await cancelBtn.click();
  await sleep(200);
  const authMaskAfter = await page.$('#authMask.show');
  expect(authMaskAfter).toBeNull();
});

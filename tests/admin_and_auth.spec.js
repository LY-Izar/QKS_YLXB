const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 390, height: 844 } });

function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

test('BUG1: init探针select包含admin_level和sub_perms字段', async ({ page }) => {
  await page.goto(SITE);
  const html = await page.content();
  const initMatch = html.match(/sbFetch\('users\?limit=1&select=[^']+' \+ encodeURIComponent\(currentUser\)\)/);
  const initStr = initMatch ? initMatch[0] : '';
  expect(initStr).toContain('admin_level');
  expect(initStr).toContain('sub_perms');
});

test('BUG1: 云探针后权限变化会调用 updateUserUI', async ({ page }) => {
  await page.goto(SITE);
  const html = await page.content();
  expect(html).toMatch(/levelChanged \|\| permsChanged[\s\S]{0,220}updateUserUI\(\)/);
});

test('BUG2: 登录模态框有取消按钮 点击后关闭', async ({ page }) => {
  await page.goto(SITE);
  await page.click('#btnLogin');
  await sleep(400);
  const mask = await page.$('#authMask.show');
  expect(mask).not.toBeNull();
  const btnTexts = await page.$$eval('#authMask .btn', els => els.map(e => (e.textContent || '').trim()));
  const hasCancel = btnTexts.some(t => t.includes('取消') || t.includes('暂不登录') || t.includes('关闭'));
  expect(hasCancel).toBeTruthy();
  const btns = await page.$$('#authMask .btn');
  let cancelBtn = null;
  for (const b of btns) { const t = await b.textContent(); if (t && (t.includes('取消')||t.includes('暂不登录')||t.includes('关闭'))) { cancelBtn = b; break; } }
  expect(cancelBtn).not.toBeNull();
  await cancelBtn.click();
  await sleep(300);
  const mask2 = await page.$('#authMask.show');
  expect(mask2).toBeNull();
});

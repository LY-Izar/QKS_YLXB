const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 1280, height: 900 } });

test('禁用本地登录回退: doLogin函数不再包含localVerify调用', async ({ page }) => {
  await page.goto(SITE);
  const src = await page.evaluate(() => {
    return doLogin.toString();
  });
  expect(src).not.toContain('localVerify');
});

test('禁用本地登录回退: doLogin函数不再包含本地IndexedDB验证回退逻辑', async ({ page }) => {
  await page.goto(SITE);
  const src = await page.evaluate(() => {
    return doLogin.toString();
  });
  expect(src).not.toContain("const rec = await DB.get('users', u)");
  expect(src).not.toContain('if(!code && !wrongPass)');
});

test('禁用本地登录回退: doLogin函数只包含云端验证流程', async ({ page }) => {
  await page.goto(SITE);
  const src = await page.evaluate(() => {
    return doLogin.toString();
  });
  expect(src).toContain('cloudUsable()');
  expect(src).toContain("sbFetch('users?select=id,pass_hash");
  expect(src).toContain('netFail = true');
});

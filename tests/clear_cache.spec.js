const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 1280, height: 900 } });

test.describe('切换账号清理本地缓存', () => {

  test('DB.clearUserData 函数存在且可调用', async ({ page }) => {
    await page.goto(SITE);
    const result = await page.evaluate(() => {
      return typeof DB.clearUserData === 'function';
    });
    expect(result).toBe(true);
  });

  test('switchUser 函数存在', async ({ page }) => {
    await page.goto(SITE);
    const result = await page.evaluate(() => {
      return typeof switchUser === 'function';
    });
    expect(result).toBe(true);
  });

  test('doLogout 函数调用 DB.clearUserData', async ({ page }) => {
    await page.goto(SITE);
    const hasClearCall = await page.evaluate(() => {
      const code = doLogout.toString();
      return code.includes('DB.clearUserData()');
    });
    expect(hasClearCall).toBe(true);
  });

  test('switchUser 函数调用 DB.clearUserData', async ({ page }) => {
    await page.goto(SITE);
    const hasClearCall = await page.evaluate(() => {
      const code = switchUser.toString();
      return code.includes('DB.clearUserData()');
    });
    expect(hasClearCall).toBe(true);
  });

  test('openAuth 在用户已登录时调用 DB.clearUserData', async ({ page }) => {
    await page.goto(SITE);
    const hasClearCall = await page.evaluate(() => {
      const code = openAuth.toString();
      return code.includes('DB.clearUserData()') && code.includes('if(currentUser)');
    });
    expect(hasClearCall).toBe(true);
  });

  test('DB.clearUserData 清理指定的 stores', async ({ page }) => {
    await page.goto(SITE);
    const clearCode = await page.evaluate(() => {
      return DB.clearUserData.toString();
    });
    
    expect(clearCode).toContain('meds');
    expect(clearCode).toContain('events');
    expect(clearCode).toContain('chronic');
    expect(clearCode).toContain('metrics');
    expect(clearCode).toContain('followups');
    expect(clearCode).toContain('medlog');
  });

});

const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 1280, height: 900 } });

test.describe('账号数据保留与隔离', () => {

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

  test('doLogout 不得销毁本地业务数据（不再调用 DB.clearUserData）', async ({ page }) => {
    await page.goto(SITE);
    const hasClearCall = await page.evaluate(() => {
      const code = doLogout.toString();
      return code.includes('DB.clearUserData()');
    });
    expect(hasClearCall).toBe(false);
  });

  test('switchUser 不得销毁本地业务数据（不再调用 DB.clearUserData）', async ({ page }) => {
    await page.goto(SITE);
    const hasClearCall = await page.evaluate(() => {
      const code = switchUser.toString();
      return code.includes('DB.clearUserData()');
    });
    expect(hasClearCall).toBe(false);
  });

  test('openAuth 打开弹窗时不得清空业务数据（不再调用 DB.clearUserData）', async ({ page }) => {
    await page.goto(SITE);
    const hasClearCall = await page.evaluate(() => {
      const code = openAuth.toString();
      return code.includes('DB.clearUserData()');
    });
    expect(hasClearCall).toBe(false);
  });

  test('业务写入必须携带 账号|身份 双维度 scope 隔离戳', async ({ page }) => {
    await page.goto(SITE);
    const result = await page.evaluate(() => {
      const withUsernameSrc = withUsername.toString();
      const allMineSrc = allMine.toString();
      const hasScopeStamp = withUsernameSrc.includes('scope');
      const hasScopeFilter = allMineSrc.includes('scopeOf') || allMineSrc.includes('scope');
      const hasRole = withUsernameSrc.includes('myRole') || withUsernameSrc.includes('activeScope');
      return { hasScopeStamp, hasScopeFilter, hasRole };
    });
    expect(result.hasScopeStamp).toBe(true);
    expect(result.hasScopeFilter).toBe(true);
    expect(result.hasRole).toBe(true);
  });

  test('DB.clearUserData 清理指定的 stores（保留为手动兜底能力）', async ({ page }) => {
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

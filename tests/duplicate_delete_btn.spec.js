const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 1280, height: 900 } });

test.describe('删除数据按钮重复修复', () => {

  test('adminLoadUsers中删除数据按钮只添加一次', async ({ page }) => {
    await page.goto(SITE);
    
    const hasDuplicate = await page.evaluate(() => {
      const code = adminLoadUsers.toString();
      
      const firstCount = (code.match(/adminOpenDeleteUserDataModal/g) || []).length;
      
      return firstCount <= 3;
    });
    
    expect(hasDuplicate).toBe(true);
  });

  test('super管理员分支中不再包含删除数据按钮', async ({ page }) => {
    await page.goto(SITE);
    
    const isFixed = await page.evaluate(() => {
      const code = adminLoadUsers.toString();
      
      const superBlockMatch = code.match(/if\(adminLevel === 'super'\)\{[\s\S]*?\} else \{/);
      if(!superBlockMatch) return false;
      
      const superBlock = superBlockMatch[0];
      return !superBlock.includes('删除数据');
    });
    
    expect(isFixed).toBe(true);
  });

});

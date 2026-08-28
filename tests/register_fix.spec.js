const { test, expect } = require('@playwright/test');

const SITE = 'http://localhost:8080/';

test.use({ viewport: { width: 1280, height: 900 } });

test('注册修复: doRegister函数包含cloudVerified变量', async ({ page }) => {
  await page.goto(SITE);
  const src = await page.evaluate(() => {
    return doRegister.toString();
  });
  expect(src).toContain('cloudVerified');
});

test('注册修复: doRegister函数云端检查成功后跳过本地检查', async ({ page }) => {
  await page.goto(SITE);
  const src = await page.evaluate(() => {
    return doRegister.toString();
  });
  expect(src).toContain('cloudVerified = true');
  expect(src).toContain('!cloudVerified && await DB.get');
});

test('注册修复: auth_check_user_exists函数已部署到数据库', async ({ page }) => {
  await page.goto(SITE);
  const result = await page.evaluate(async () => {
    try {
      const SB_URL = 'https://hjryfgujkxuaxovftlai.supabase.co';
      const SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NTcwNjUsImV4cCI6MjEwMzEzMzA2NX0.VsGxfhBt1J6iVYiZNyWhaeI_MSYnxSCaVFHgco1wKbc';
      const res = await fetch(SB_URL + '/rest/v1/rpc/auth_check_user_exists', {
        method: 'POST',
        headers: {
          apikey: SB_KEY,
          'Authorization': 'Bearer ' + SB_KEY,
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ username: 'nonexistent_user_12345' })
      });
      if (res.ok) {
        const json = await res.json();
        return { exists: json.exists, reason: json.reason };
      }
      return { error: 'HTTP ' + res.status };
    } catch (e) {
      return { error: e.message };
    }
  });
  expect(result.exists).toBe(false);
  expect(result.reason).toBe('none');
});

test('注册修复: auth_check_user_exists对已存在账户返回exists=true', async ({ page }) => {
  await page.goto(SITE);
  const result = await page.evaluate(async () => {
    try {
      const SB_URL = 'https://hjryfgujkxuaxovftlai.supabase.co';
      const SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhqcnlmZ3Vqa3h1YXhvdmZ0bGFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NTcwNjUsImV4cCI6MjEwMzEzMzA2NX0.VsGxfhBt1J6iVYiZNyWhaeI_MSYnxSCaVFHgco1wKbc';
      const res = await fetch(SB_URL + '/rest/v1/rpc/auth_check_user_exists', {
        method: 'POST',
        headers: {
          apikey: SB_KEY,
          'Authorization': 'Bearer ' + SB_KEY,
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ username: 'CESHI' })
      });
      if (res.ok) {
        const json = await res.json();
        return { exists: json.exists, reason: json.reason };
      }
      return { error: 'HTTP ' + res.status };
    } catch (e) {
      return { error: e.message };
    }
  });
  expect(result.exists).toBe(true);
  expect(result.reason).toBe('cloud');
});

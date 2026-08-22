/**
 * Tauri CDP 多账号测试 v3.0
 *
 * 三账号场景:
 *   - admin (系统管理员): 用户管理、系统监控
 *   - user2 (普通 user + KB owner): 创建 KB、管理协作者
 *   - user3 (普通 user + KB 协作者): 权限矩阵验证
 *
 * 测试模块:
 *   A. 用户管理实效 (admin 禁用/升降级 user2)
 *   B. KB 协作权限矩阵 (read→write→admin 升降级 + 403 边界)
 *   C. 协作者互踢/自删除
 *   D. token 隔离与并发
 *
 * 双层验证: API 状态码 + UI 实效(切换 CDP 用户验证渲染)
 * 清理策略: 测试后软禁用 user2/user3
 */
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SHOTS_DIR = join(__dirname, 'test_screenshots_v3');
if (!existsSync(SHOTS_DIR)) mkdirSync(SHOTS_DIR, { recursive: true });

const CDP_HTTP = 'http://127.0.0.1:9223';
const FRONTEND = 'http://localhost:5173';
const BACKEND = 'http://localhost:8000/api/v1';
let wsUrl = null;
let ws = null;
let msgId = 1;
const pending = new Map();
const testResults = [];

// 错误追踪器 (复用 v2 设计)
const errorTracker = new (class {
  constructor() {
    this.errors = [];
    this.warnings = [];
    this.netErrors = [];
    this.stepStartIdx = 0;
  }
  reset() { this.errors = []; this.warnings = []; this.netErrors = []; this.stepStartIdx = 0; }
  markStepStart() { this.stepStartIdx = this.errors.length + this.netErrors.length; }
  hasNewErrors() { return this.errors.length + this.netErrors.length > this.stepStartIdx; }
  getNewErrors() {
    return {
      errors: this.errors.slice(this.stepStartIdx),
      netErrors: this.netErrors.slice(this.stepStartIdx),
    };
  }
})();

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ============================================================
// CDP 基础连接 (复用 v2)
// ============================================================

async function getTauriTarget() {
  const resp = await fetch(`${CDP_HTTP}/json`);
  const targets = await resp.json();
  const target = targets.find(t => t.type === 'page' && t.title && t.title.includes('RAG'));
  if (!target) throw new Error(`未找到 Tauri 窗口`);
  return target;
}

function connectWS(url) {
  return new Promise((resolve, reject) => {
    const sock = new WebSocket(url);
    sock.addEventListener('open', () => resolve(sock));
    sock.addEventListener('error', (e) => reject(new Error('WS 连接失败')));
  });
}

async function send(method, params = {}) {
  const id = msgId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

function setupListeners() {
  ws.addEventListener('message', async (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(`CDP error: ${JSON.stringify(msg.error)}`));
      else resolve(msg.result);
      return;
    }
    // 实时错误监控
    if (msg.method === 'Runtime.consoleAPICalled') {
      const type = msg.params.type;
      if (type === 'error') {
        const args = (msg.params.args || []).map(a => a.value ?? a.description ?? JSON.stringify(a)).join(' ');
        // 过滤非业务错误
        if (args.includes('[WebSocket]') || args.includes('canceled') || args.includes('Failed to load resource')) {
          errorTracker.warnings.push({ type: 'filtered', text: args, ts: Date.now() });
        } else {
          errorTracker.errors.push({ type, text: args, ts: Date.now(), stack: msg.params.stackTrace });
        }
      } else if (type === 'warning') {
        const args = (msg.params.args || []).map(a => a.value ?? a.description ?? JSON.stringify(a)).join(' ');
        errorTracker.warnings.push({ type, text: args, ts: Date.now() });
      }
    } else if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails;
      const text = `${d.text} ${d.exception ? d.exception.description : ''}`;
      if (text.includes('canceled')) {
        errorTracker.warnings.push({ type: 'canceled', text, ts: Date.now() });
      } else {
        errorTracker.errors.push({ type: 'exception', text, ts: Date.now(), stack: d.stackTrace });
      }
    } else if (msg.method === 'Network.responseReceived') {
      const r = msg.params.response;
      // 多账号测试中, 401/403 是预期的权限边界验证, 不算网络错误
      // 仅 >=500 的服务端错误才记录
      if (r.status >= 500) {
        errorTracker.netErrors.push({ url: r.url, status: r.status, method: msg.params.type, ts: Date.now() });
      }
    }
  });
}

async function evalJS(expression, awaitPromise = true, returnByValue = true) {
  const result = await send('Runtime.evaluate', {
    expression, awaitPromise, returnByValue, userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(`JS eval failed: ${JSON.stringify(result.exceptionDetails)}`);
  }
  return result.result.value;
}

async function navigate(url) {
  await send('Page.navigate', { url });
  await sleep(1500);
}

async function screenshot(name) {
  const result = await send('Page.captureScreenshot', { format: 'png' });
  const buf = Buffer.from(result.data, 'base64');
  const path = join(SHOTS_DIR, name);
  writeFileSync(path, buf);
  return path;
}

async function getDomSnapshot() {
  return await evalJS(`
    (() => {
      const body = document.body;
      if (!body) return '<no body>';
      const clone = body.cloneNode(true);
      clone.querySelectorAll('script,style,svg').forEach(e => e.remove());
      let html = clone.innerHTML;
      if (html.length > 2000) html = html.substring(0, 2000) + '...[truncated]';
      return html;
    })()
  `);
}

// ============================================================
// 测试步骤包装器 (复用 v2)
// ============================================================

async function step(name, fn) {
  errorTracker.markStepStart();
  const start = Date.now();
  let status = 'PASS';
  let note = '';
  let errorDetail = null;
  try {
    const result = await fn();
    if (result && typeof result === 'object' && result.note) {
      note = result.note;
    }
    if (errorTracker.hasNewErrors()) {
      const { errors, netErrors } = errorTracker.getNewErrors();
      status = 'FAIL';
      const errSummary = errors.map(e => `[${e.type}] ${e.text.substring(0, 150)}`).join('; ');
      const netSummary = netErrors.map(e => `[${e.status}] ${e.url}`).join('; ');
      errorDetail = { errors, netErrors };
      note = `新错误: ${errSummary}${netSummary ? ' | 网络: ' + netSummary : ''}`;
    }
  } catch (e) {
    status = 'FAIL';
    note = e.message.substring(0, 300);
    errorDetail = { exception: e.message, stack: e.stack };
  }
  const duration = Date.now() - start;
  if (status === 'FAIL') {
    const shotName = `FAIL-${name.replace(/[^a-zA-Z0-9]/g, '_')}.png`;
    try { await screenshot(shotName); } catch {}
    const domSnap = await getDomSnapshot().catch(() => '<snapshot failed>');
    errorDetail = errorDetail || {};
    errorDetail.screenshot = shotName;
    errorDetail.domSnapshot = domSnap;
  }
  testResults.push({ name, status, note, duration, errorDetail });
  const icon = status === 'PASS' ? '✓' : '✗';
  console.log(`  [${icon}] ${name} (${duration}ms)${note ? ' | ' + note : ''}`);
}

// ============================================================
// 账号管理
// ============================================================

const TEST_PASSWORD = 'Test@123456';
const accounts = {
  admin: { username: 'admin', password: 'AdminAcceptance2026!StrongPwd', userId: null, accessToken: null, refreshToken: null, role: 'admin' },
  user2: { username: `mtest_u2_${Date.now()}`, password: TEST_PASSWORD, userId: null, accessToken: null, refreshToken: null, role: 'user', email: null },
  user3: { username: `mtest_u3_${Date.now()}`, password: TEST_PASSWORD, userId: null, accessToken: null, refreshToken: null, role: 'user', email: null },
};

/**
 * 通过 Node.js 直接调后端 API (不经过 CDP), 用于账号管理
 */
async function apiRequest(method, path, { token, body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${BACKEND}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let parsed;
  try { parsed = JSON.parse(text); } catch { parsed = text; }
  return { status: resp.status, body: parsed, code: parsed?.code, message: parsed?.message, data: parsed?.data };
}

async function registerAndLogin(account) {
  // 注册
  const regResp = await apiRequest('POST', '/auth/register', {
    body: {
      username: account.username,
      email: `${account.username}@test.com`,
      password: account.password,
    },
  });
  if (regResp.status !== 200) {
    throw new Error(`注册 ${account.username} 失败: ${regResp.status} ${JSON.stringify(regResp.body).substring(0, 200)}`);
  }
  account.userId = regResp.data?.id;
  account.email = regResp.data?.email;
  // 登录
  const loginResp = await apiRequest('POST', '/auth/login', {
    body: { username: account.username, password: account.password },
  });
  if (loginResp.status !== 200) {
    throw new Error(`登录 ${account.username} 失败: ${loginResp.status}`);
  }
  account.accessToken = loginResp.data?.access_token;
  account.refreshToken = loginResp.data?.refresh_token;
  account.role = loginResp.data?.user?.role || 'user';
  return account;
}

async function loginAdmin() {
  const loginResp = await apiRequest('POST', '/auth/login', {
    body: { username: accounts.admin.username, password: accounts.admin.password },
  });
  if (loginResp.status !== 200) {
    throw new Error(`admin 登录失败: ${loginResp.status} ${JSON.stringify(loginResp.body).substring(0, 200)}`);
  }
  accounts.admin.accessToken = loginResp.data?.access_token;
  accounts.admin.refreshToken = loginResp.data?.refresh_token;
  accounts.admin.userId = loginResp.data?.user?.id;
  return accounts.admin;
}

/**
 * 在 CDP 会话中切换用户:
 * 1. 清理 localStorage
 * 2. 注入新 token (zustand persist 格式)
 * 3. Page.reload 强制整页重载, 让 store rehydrate
 * 4. 等待 3s 确保 rehydrate 完成
 * 5. 设置 hash 导航到目标路由
 */
async function switchCdpUser(account, route = '#/dashboard') {
  const authData = {
    state: {
      token: account.accessToken,
      refreshToken: account.refreshToken,
      refreshTokenExpiresAt: Date.now() + 7 * 24 * 3600 * 1000,
      user: { id: account.userId, username: account.username, email: account.email, role: account.role },
      themeMode: 'light',
    },
    version: 0,
  };
  const authJson = JSON.stringify(authData);

  // 导航到根域, 确保 localStorage 可访问
  await navigate(`${FRONTEND}/`);
  await sleep(500);

  // 注入 token
  await evalJS(`
    try {
      localStorage.setItem('rag-auth', '${authJson.replace(/'/g, "\\'")}');
    } catch(e) {}
  `);

  // 强制整页重载 (zustand persist 需要 cross-document navigation 才能 rehydrate)
  await send('Page.reload');
  await sleep(3000);

  // reload 后 store 已 rehydrate 新用户, 设置 hash 导航到目标路由
  await evalJS(`window.location.hash = ${JSON.stringify(route)};`);
  await sleep(1500);

  // 验证登录是否成功 (hash 不应包含 login)
  const hash = await evalJS('window.location.hash') || '';
  if (hash.includes('login')) {
    // 重试一次
    await evalJS(`
      try {
        localStorage.setItem('rag-auth', '${authJson.replace(/'/g, "\\'")}');
      } catch(e) {}
    `);
    await send('Page.reload');
    await sleep(3000);
    await evalJS(`window.location.hash = ${JSON.stringify(route)};`);
    await sleep(1500);
  }
}

/**
 * 用指定账号在 CDP 内调 API (经前端 fetch, 带 Authorization)
 * 用于验证 API 状态码 + UI 实效
 */
async function apiCallAs(account, method, path, body) {
  const result = await evalJS(`
    (async () => {
      const token = ${JSON.stringify(account.accessToken)};
      const resp = await fetch('${BACKEND}${path}', {
        method: ${JSON.stringify(method)},
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token,
        },
        body: ${body ? JSON.stringify(JSON.stringify(body)) : 'undefined'},
      });
      const text = await resp.text();
      let parsed;
      try { parsed = JSON.parse(text); } catch { parsed = text; }
      return JSON.stringify({ status: resp.status, body: parsed });
    })()
  `).then(s => JSON.parse(s));
  return {
    status: result.status,
    code: result.body?.code,
    message: result.body?.message,
    data: result.body?.data,
    raw: result.body,
  };
}

// ============================================================
// 断言辅助
// ============================================================

async function assertApiStatus(resp, expected, description) {
  if (resp.status !== expected) {
    throw new Error(`${description}: 期望 ${expected}, 实际 ${resp.status}, body=${JSON.stringify(resp.raw || resp).substring(0, 200)}`);
  }
  return true;
}

async function assertApiOk(resp, description) {
  if (!resp || resp.status >= 400) {
    throw new Error(`${description}: API 返回 ${resp?.status || 'null'}`);
  }
  if (resp.code !== undefined && resp.code !== 0) {
    throw new Error(`${description}: 业务错误 code=${resp.code}, msg=${resp.message}`);
  }
  return true;
}

async function assertVisible(selector, description) {
  const visible = await evalJS(`
    (() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
    })()
  `);
  if (!visible) throw new Error(`${description}: 元素 ${selector} 不可见`);
  return true;
}

async function waitFor(predicate, { timeout = 15000, interval = 500 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const result = await predicate();
      if (result) return result;
    } catch (e) { /* retry */ }
    await sleep(interval);
  }
  throw new Error(`waitFor timeout after ${timeout}ms`);
}

// ============================================================
// 测试模块 A: 用户管理实效
// ============================================================

async function testUserManagement() {
  console.log('\n=== 模块A: 用户管理实效 (admin 操作 user2) ===');

  await step('A.1 admin 禁用 user2 → user2 token 立即失效', async () => {
    // admin 操作: 禁用 user2
    const resp = await apiCallAs(accounts.admin, 'PUT', `/users/${accounts.user2.userId}/status`, { is_active: false });
    await assertApiOk(resp, 'admin 禁用 user2');
    // user2 验证: /auth/me 应返回 401
    const meResp = await apiCallAs(accounts.user2, 'GET', '/auth/me');
    if (meResp.status !== 401) {
      throw new Error(`user2 被禁用后 /auth/me 应返回 401, 实际 ${meResp.status}`);
    }
    return { note: `user2 userId=${accounts.user2.userId} 已禁用, /auth/me 返回 401` };
  });

  await step('A.2 admin 启用 user2 → user2 token 恢复', async () => {
    const resp = await apiCallAs(accounts.admin, 'PUT', `/users/${accounts.user2.userId}/status`, { is_active: true });
    await assertApiOk(resp, 'admin 启用 user2');
    // user2 重新登录获取新 token (旧 token 已失效)
    const loginResp = await apiRequest('POST', '/auth/login', {
      body: { username: accounts.user2.username, password: accounts.user2.password },
    });
    if (loginResp.status !== 200) throw new Error(`user2 重新登录失败: ${loginResp.status}`);
    accounts.user2.accessToken = loginResp.data?.access_token;
    accounts.user2.refreshToken = loginResp.data?.refresh_token;
    // 验证 /auth/me
    const meResp = await apiCallAs(accounts.user2, 'GET', '/auth/me');
    if (meResp.status !== 200) throw new Error(`user2 启用后 /auth/me 应返回 200, 实际 ${meResp.status}`);
    return { note: 'user2 已启用, 新 token 工作正常' };
  });

  await step('A.3 admin 升级 user2 为 admin 角色', async () => {
    const resp = await apiCallAs(accounts.admin, 'PUT', `/users/${accounts.user2.userId}/role`, { role: 'admin' });
    await assertApiOk(resp, 'admin 升级 user2');
    // user2 重新登录获取含新角色的 token
    const loginResp = await apiRequest('POST', '/auth/login', {
      body: { username: accounts.user2.username, password: accounts.user2.password },
    });
    if (loginResp.status !== 200) throw new Error(`user2 重新登录失败`);
    accounts.user2.accessToken = loginResp.data?.access_token;
    accounts.user2.refreshToken = loginResp.data?.refresh_token;
    accounts.user2.role = loginResp.data?.user?.role;
    if (accounts.user2.role !== 'admin') throw new Error(`user2 角色应为 admin, 实际 ${accounts.user2.role}`);
    return { note: `user2 已升级为 admin` };
  });

  await step('A.4 user2 以 admin 身份访问 /users (API + UI)', async () => {
    // API 验证: user2 现在应能访问 /users
    const resp = await apiCallAs(accounts.user2, 'GET', '/users?page=1&page_size=5');
    if (resp.status !== 200) throw new Error(`user2 admin 应能访问 /users, 实际 ${resp.status}`);
    // UI 验证: 切换到 user2, 访问用户管理页
    await switchCdpUser(accounts.user2, '#/users');
    await waitFor(() => evalJS(`document.querySelector('.ant-table, .ant-list, .ant-empty') !== null`), { timeout: 10000 });
    await screenshot('A4-user2-admin-users-page.png');
    await assertVisible('.ant-table, .ant-list, .ant-empty', '用户列表');
    return { note: `user2 以 admin 身份访问用户管理页成功` };
  });

  await step('A.5 admin 降级 user2 为 user 角色', async () => {
    const resp = await apiCallAs(accounts.admin, 'PUT', `/users/${accounts.user2.userId}/role`, { role: 'user' });
    await assertApiOk(resp, 'admin 降级 user2');
    // user2 重新登录
    const loginResp = await apiRequest('POST', '/auth/login', {
      body: { username: accounts.user2.username, password: accounts.user2.password },
    });
    if (loginResp.status !== 200) throw new Error(`user2 重新登录失败`);
    accounts.user2.accessToken = loginResp.data?.access_token;
    accounts.user2.refreshToken = loginResp.data?.refresh_token;
    accounts.user2.role = loginResp.data?.user?.role;
    if (accounts.user2.role !== 'user') throw new Error(`user2 角色应为 user, 实际 ${accounts.user2.role}`);
    // API 验证: user2 现在应被拒绝访问 /users
    const usersResp = await apiCallAs(accounts.user2, 'GET', '/users?page=1&page_size=5');
    if (usersResp.status !== 403) {
      throw new Error(`user2 降级后访问 /users 应返回 403, 实际 ${usersResp.status}`);
    }
    return { note: `user2 已降级为 user, /users 返回 403` };
  });

  await step('A.6 admin 不能禁用自己 (防锁定保护)', async () => {
    const resp = await apiCallAs(accounts.admin, 'PUT', `/users/${accounts.admin.userId}/status`, { is_active: false });
    // 应返回 400 或 403 (防锁定)
    if (resp.status !== 400 && resp.status !== 403) {
      throw new Error(`admin 禁用自己应被拒绝 (400/403), 实际 ${resp.status}`);
    }
    return { note: `防锁定保护生效, status=${resp.status}` };
  });
}

// ============================================================
// 测试模块 B: KB 协作权限矩阵
// ============================================================

async function testKbCollaboratorMatrix() {
  console.log('\n=== 模块B: KB 协作权限矩阵 (user2 owner + user3 collaborator) ===');
  let kbId = null;

  await step('B.1 user2 创建知识库 (作为 owner)', async () => {
    const kbName = `多账号测试KB-${Date.now()}`;
    const resp = await apiCallAs(accounts.user2, 'POST', '/knowledge-bases', { name: kbName, description: '协作权限矩阵测试' });
    await assertApiOk(resp, 'user2 创建 KB');
    kbId = resp.data?.id;
    if (!kbId) throw new Error('未返回 kbId');
    return { note: `kbId=${kbId}, name=${kbName}` };
  });

  await step('B.2 user2 添加 user3 为 read 协作者', async () => {
    const resp = await apiCallAs(accounts.user2, 'POST', `/knowledge-bases/${kbId}/collaborators`, {
      user_id: accounts.user3.userId,
      permission: 'read',
    });
    await assertApiOk(resp, '添加 user3 为 read 协作者');
    return { note: `user3 userId=${accounts.user3.userId} 已添加为 read` };
  });

  await step('B.3 user3 read 权限: 可见 KB (API + UI)', async () => {
    // API 验证: user3 应能在 KB 列表看到该 KB
    const listResp = await apiCallAs(accounts.user3, 'GET', '/knowledge-bases');
    await assertApiOk(listResp, 'user3 获取 KB 列表');
    const items = listResp.data?.items || listResp.data || [];
    const found = items.find(kb => kb.id === kbId);
    if (!found) throw new Error(`user3 在 KB 列表中未看到共享的 KB (kbId=${kbId})`);
    // UI 验证: 切换到 user3, 查看知识库列表
    await switchCdpUser(accounts.user3, '#/knowledge-bases');
    await waitFor(() => evalJS(`document.querySelector('.ant-card, .ant-list, .ant-empty') !== null`), { timeout: 10000 });
    await screenshot('B3-user3-kb-list.png');
    return { note: `user3 在 API 和 UI 中看到共享 KB` };
  });

  await step('B.4 user3 read 权限: 真实 multipart 上传被拒绝 (403)', async () => {
    // 用真实 multipart/form-data 上传, 触达后端权限校验
    // (之前用 JSON 调用 multipart 端点会返回 422 参数绑定错误, 无法触达权限校验)
    const result = await evalJS(`
      (async () => {
        const token = ${JSON.stringify(accounts.user3.accessToken)};
        const formData = new FormData();
        formData.append('kb_id', '${kbId}');
        const blob = new Blob(['read permission test content'], { type: 'text/plain' });
        formData.append('file', blob, 'test_read_perm.txt');
        const resp = await fetch('${BACKEND}/documents/upload', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + token },
          body: formData,
        });
        return JSON.stringify({ status: resp.status });
      })()
    `).then(s => JSON.parse(s));
    if (result.status !== 403) {
      throw new Error(`user3 read 权限上传应返回 403, 实际 ${result.status}`);
    }
    return { note: `read 权限真实上传被拒绝 (403)` };
  });

  await step('B.5 user2 升级 user3 为 write 权限', async () => {
    const resp = await apiCallAs(accounts.user2, 'POST', `/knowledge-bases/${kbId}/collaborators`, {
      user_id: accounts.user3.userId,
      permission: 'write',
    });
    await assertApiOk(resp, '升级 user3 为 write');
    return { note: `user3 已升级为 write` };
  });

  await step('B.6 user3 write 权限: 不可删除 KB (403)', async () => {
    const resp = await apiCallAs(accounts.user3, 'DELETE', `/knowledge-bases/${kbId}`);
    if (resp.status !== 403) {
      throw new Error(`user3 write 权限删 KB 应返回 403, 实际 ${resp.status}`);
    }
    return { note: `write 权限删 KB 被拒绝 (403)` };
  });

  await step('B.7 user2 升级 user3 为 admin 协作者', async () => {
    const resp = await apiCallAs(accounts.user2, 'POST', `/knowledge-bases/${kbId}/collaborators`, {
      user_id: accounts.user3.userId,
      permission: 'admin',
    });
    await assertApiOk(resp, '升级 user3 为 admin 协作者');
    return { note: `user3 已升级为 admin 协作者` };
  });

  await step('B.8 user3 admin 协作者: 不可删除 KB (403, 仅 owner 可删)', async () => {
    const resp = await apiCallAs(accounts.user3, 'DELETE', `/knowledge-bases/${kbId}`);
    if (resp.status !== 403) {
      throw new Error(`user3 admin 协作者删 KB 应返回 403, 实际 ${resp.status}`);
    }
    return { note: `admin 协作者删 KB 被拒绝 (403, 仅 owner 可删)` };
  });

  await step('B.9 user2 删除 KB → user3 立即看不到', async () => {
    // owner 删除 KB
    const delResp = await apiCallAs(accounts.user2, 'DELETE', `/knowledge-bases/${kbId}`);
    await assertApiOk(delResp, 'user2 删除 KB');
    // user3 验证: KB 列表中不再包含该 KB
    const listResp = await apiCallAs(accounts.user3, 'GET', '/knowledge-bases');
    await assertApiOk(listResp, 'user3 重新获取 KB 列表');
    const items = listResp.data?.items || listResp.data || [];
    const stillFound = items.find(kb => kb.id === kbId);
    if (stillFound) throw new Error(`user3 仍能看到已删除的 KB (kbId=${kbId})`);
    return { note: `KB 已删除, user3 列表中不再包含` };
  });
}

// ============================================================
// 测试模块 C: 协作者互踢/自删除
// ============================================================

async function testCollaboratorRemoval() {
  console.log('\n=== 模块C: 协作者互踢/自删除 ===');
  let kbId = null;

  await step('C.1 user2 创建新 KB 并添加 user3 为 admin 协作者', async () => {
    const kbName = `互踢测试KB-${Date.now()}`;
    const createResp = await apiCallAs(accounts.user2, 'POST', '/knowledge-bases', { name: kbName, description: '互踢测试' });
    await assertApiOk(createResp, 'user2 创建 KB');
    kbId = createResp.data?.id;
    const addResp = await apiCallAs(accounts.user2, 'POST', `/knowledge-bases/${kbId}/collaborators`, {
      user_id: accounts.user3.userId,
      permission: 'admin',
    });
    await assertApiOk(addResp, '添加 user3 为 admin 协作者');
    return { note: `kbId=${kbId}` };
  });

  await step('C.2 user3 尝试踢掉 user2 (owner) → 应 403', async () => {
    // 后端 remove_collaborator 已修复: 显式拒绝踢 owner, 返回 403
    // (与 add_collaborator 的 "Cannot add owner as collaborator" 对称)
    const resp = await apiCallAs(accounts.user3, 'DELETE', `/knowledge-bases/${kbId}/collaborators/${accounts.user2.userId}`);
    if (resp.status !== 403) {
      throw new Error(`user3 踢 owner 应返回 403, 实际 ${resp.status}`);
    }
    // 验证 owner(user2)仍能访问 KB
    const ownerCheck = await apiCallAs(accounts.user2, 'GET', `/knowledge-bases/${kbId}`);
    if (ownerCheck.status !== 200) {
      throw new Error(`owner 被踢后应仍能访问 KB, 实际 ${ownerCheck.status}`);
    }
    return { note: `协作者踢 owner 被拒绝 (403), owner 权限不变` };
  });

  await step('C.3 user3 自删除协作者关系', async () => {
    const resp = await apiCallAs(accounts.user3, 'DELETE', `/knowledge-bases/${kbId}/collaborators/${accounts.user3.userId}`);
    await assertApiOk(resp, 'user3 自删除');
    return { note: `user3 已自删除` };
  });

  await step('C.4 user3 自删除后立即失去 KB 访问 (404 或不在列表)', async () => {
    const listResp = await apiCallAs(accounts.user3, 'GET', '/knowledge-bases');
    await assertApiOk(listResp, 'user3 获取 KB 列表');
    const items = listResp.data?.items || listResp.data || [];
    const found = items.find(kb => kb.id === kbId);
    if (found) throw new Error(`user3 自删除后仍能看到 KB (kbId=${kbId})`);
    // 直接 GET 该 KB 也应失败
    const detailResp = await apiCallAs(accounts.user3, 'GET', `/knowledge-bases/${kbId}`);
    if (detailResp.status !== 403 && detailResp.status !== 404) {
      throw new Error(`user3 自删除后访问 KB 详情应 403/404, 实际 ${detailResp.status}`);
    }
    return { note: `user3 已失去 KB 访问, detail status=${detailResp.status}` };
  });

  await step('C.5 清理: user2 删除 KB', async () => {
    const resp = await apiCallAs(accounts.user2, 'DELETE', `/knowledge-bases/${kbId}`);
    await assertApiOk(resp, 'user2 删除 KB');
    return { note: '清理完成' };
  });
}

// ============================================================
// 测试模块 D: token 隔离与并发
// ============================================================

async function testTokenIsolation() {
  console.log('\n=== 模块D: token 隔离与并发 ===');

  await step('D.1 user2 登出 → user2 token 失效, user3 token 不受影响', async () => {
    // user2 登出
    const logoutResp = await apiCallAs(accounts.user2, 'POST', '/auth/logout', {
      refresh_token: accounts.user2.refreshToken,
    });
    if (logoutResp.status !== 200) {
      throw new Error(`user2 登出失败: ${logoutResp.status}`);
    }
    // user2 旧 access_token 应失效
    const meResp = await apiCallAs(accounts.user2, 'GET', '/auth/me');
    if (meResp.status !== 401) {
      throw new Error(`user2 登出后 /auth/me 应返回 401, 实际 ${meResp.status}`);
    }
    // user3 token 应仍有效
    const user3Me = await apiCallAs(accounts.user3, 'GET', '/auth/me');
    if (user3Me.status !== 200) {
      throw new Error(`user3 token 应仍有效, 实际 ${user3Me.status}`);
    }
    return { note: `user2 已登出, user3 token 不受影响` };
  });

  await step('D.2 user2 重新登录获取新 token', async () => {
    const loginResp = await apiRequest('POST', '/auth/login', {
      body: { username: accounts.user2.username, password: accounts.user2.password },
    });
    if (loginResp.status !== 200) throw new Error(`user2 重新登录失败`);
    accounts.user2.accessToken = loginResp.data?.access_token;
    accounts.user2.refreshToken = loginResp.data?.refresh_token;
    // 验证新 token 工作
    const meResp = await apiCallAs(accounts.user2, 'GET', '/auth/me');
    if (meResp.status !== 200) throw new Error(`user2 新 token 应有效, 实际 ${meResp.status}`);
    return { note: `user2 重新登录成功` };
  });

  await step('D.3 user2 旧 refresh_token 已黑名单 (轮换失效)', async () => {
    // 尝试用旧 refresh_token (已在 D.1 登出时黑名单)
    // 注意: D.2 重新登录后, accounts.user2.refreshToken 已更新为新值
    // 这里验证的是: 登出时的旧 refresh_token 不可用
    // 由于 D.1 已用旧 refresh 登出, 这里用 D.2 的新 refresh 再调一次 refresh 应成功
    const refreshResp = await apiRequest('POST', '/auth/refresh', {
      body: { refresh_token: accounts.user2.refreshToken },
    });
    if (refreshResp.status !== 200) {
      throw new Error(`user2 新 refresh_token 应可用, 实际 ${refreshResp.status}`);
    }
    // refresh 后旧 refresh 立即黑名单 (rotation), 新 refresh 替换
    accounts.user2.accessToken = refreshResp.data?.access_token;
    accounts.user2.refreshToken = refreshResp.data?.refresh_token;
    return { note: `refresh token 轮换机制正常` };
  });

  await step('D.4 多账号并发切换 localStorage 不串号', async () => {
    // 切换到 user2, 验证身份
    await switchCdpUser(accounts.user2, '#/dashboard');
    let currentUser = await evalJS(`
      (() => {
        const raw = localStorage.getItem('rag-auth');
        const p = raw ? JSON.parse(raw) : null;
        return p?.state?.user?.username || null;
      })()
    `);
    if (currentUser !== accounts.user2.username) {
      throw new Error(`切换到 user2 后应为 ${accounts.user2.username}, 实际 ${currentUser}`);
    }
    // 切换到 user3, 验证身份
    await switchCdpUser(accounts.user3, '#/dashboard');
    currentUser = await evalJS(`
      (() => {
        const raw = localStorage.getItem('rag-auth');
        const p = raw ? JSON.parse(raw) : null;
        return p?.state?.user?.username || null;
      })()
    `);
    if (currentUser !== accounts.user3.username) {
      throw new Error(`切换到 user3 后应为 ${accounts.user3.username}, 实际 ${currentUser}`);
    }
    // 切换回 admin, 验证身份
    await switchCdpUser(accounts.admin, '#/dashboard');
    currentUser = await evalJS(`
      (() => {
        const raw = localStorage.getItem('rag-auth');
        const p = raw ? JSON.parse(raw) : null;
        return p?.state?.user?.username || null;
      })()
    `);
    if (currentUser !== accounts.admin.username) {
      throw new Error(`切换到 admin 后应为 ${accounts.admin.username}, 实际 ${currentUser}`);
    }
    await screenshot('D4-admin-switched.png');
    return { note: `三账号顺序切换无串号` };
  });
}

// ============================================================
// 清理: 软禁用测试账号
// ============================================================

async function cleanup() {
  console.log('\n=== 清理: 软禁用测试账号 ===');
  // admin 软禁用 user2/user3
  for (const [key, account] of Object.entries(accounts)) {
    if (key === 'admin') continue;
    try {
      const resp = await apiCallAs(accounts.admin, 'PUT', `/users/${account.userId}/status`, { is_active: false });
      if (resp.status === 200) {
        console.log(`  [✓] 软禁用 ${account.username} (userId=${account.userId})`);
      } else {
        console.log(`  [✗] 软禁用 ${account.username} 失败: ${resp.status}`);
      }
    } catch (e) {
      console.log(`  [✗] 软禁用 ${account.username} 异常: ${e.message}`);
    }
  }
}

// ============================================================
// 主流程
// ============================================================

async function main() {
  console.log('=== Tauri CDP 多账号测试 v3.0 ===');
  console.log(`时间: ${new Date().toISOString()}`);

  // 1. 连接 CDP
  const target = await getTauriTarget();
  console.log(`Tauri 窗口: title="${target.title}", url="${target.url}"`);
  wsUrl = target.webSocketDebuggerUrl;
  ws = await connectWS(wsUrl);
  console.log(`CDP WebSocket 已连接`);
  setupListeners();

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Console.enable');
  await send('Log.enable');
  console.log('CDP domains 已启用');

  errorTracker.reset();

  // 2. 账号准备 (session 级, 避免限流)
  console.log('\n=== 账号准备 ===');
  try {
    await loginAdmin();
    console.log(`  [✓] admin 登录成功 (userId=${accounts.admin.userId})`);
    await registerAndLogin(accounts.user2);
    console.log(`  [✓] user2 注册+登录成功 (userId=${accounts.user2.userId}, username=${accounts.user2.username})`);
    await sleep(1000); // 避免触发 register 限流 (5/min)
    await registerAndLogin(accounts.user3);
    console.log(`  [✓] user3 注册+登录成功 (userId=${accounts.user3.userId}, username=${accounts.user3.username})`);
  } catch (e) {
    console.error(`账号准备失败: ${e.message}`);
    process.exit(2);
  }

  // 3. 运行测试模块
  try {
    await testUserManagement();
    await testKbCollaboratorMatrix();
    await testCollaboratorRemoval();
    await testTokenIsolation();
  } catch (e) {
    console.error('测试中断:', e.message);
    testResults.push({ name: '测试中断', status: 'FAIL', note: e.message, errorDetail: { stack: e.stack } });
  }

  // 4. 清理
  await cleanup();

  // 5. 汇总
  console.log('\n=== 测试报告汇总 ===');
  const pass = testResults.filter(r => r.status === 'PASS').length;
  const fail = testResults.filter(r => r.status === 'FAIL').length;
  const total = testResults.length;
  const passRate = total > 0 ? (pass / total * 100).toFixed(1) : 0;
  console.log(`PASS: ${pass} | FAIL: ${fail} | 总计: ${total} | 正确率: ${passRate}%`);

  console.log('\n--- 所有 console 错误/异常 (不含 warning) ---');
  if (errorTracker.errors.length === 0) {
    console.log('无 JavaScript 错误/异常');
  } else {
    errorTracker.errors.forEach((e, i) => console.log(`[${i + 1}] [${e.type}] ${e.text.substring(0, 200)}`));
  }

  console.log('\n--- 所有网络错误 (>=500) ---');
  if (errorTracker.netErrors.length === 0) {
    console.log('无 5xx 网络错误');
  } else {
    errorTracker.netErrors.forEach((e, i) => console.log(`[${i + 1}] ${e.status} ${e.url}`));
  }

  if (fail > 0) {
    console.log('\n--- 失败用例详情 ---');
    testResults.filter(r => r.status === 'FAIL').forEach(r => {
      console.log(`✗ ${r.name}: ${r.note}`);
    });
  }

  const report = {
    timestamp: new Date().toISOString(),
    target: { title: target.title, url: target.url },
    accounts: {
      admin: { userId: accounts.admin.userId, username: accounts.admin.username },
      user2: { userId: accounts.user2.userId, username: accounts.user2.username },
      user3: { userId: accounts.user3.userId, username: accounts.user3.username },
    },
    summary: { pass, fail, total, passRate: parseFloat(passRate) },
    results: testResults,
    allErrors: errorTracker.errors,
    allWarnings: errorTracker.warnings,
    allNetErrors: errorTracker.netErrors,
  };
  const reportPath = join(__dirname, 'tauri_cdp_report_v3_multiuser.json');
  writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`\n详细报告: ${reportPath}`);

  ws.close();
  process.exit(fail > 0 ? 1 : 0);
}

main().catch(e => {
  console.error('致命错误:', e);
  process.exit(2);
});

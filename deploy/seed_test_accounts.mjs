/**
 * T1 测试账号种子脚本（multi-account-rigorous-validation SPEC）
 *
 * 创建/复用三个 user 角色测试账号，落盘 token 供后续多账号测试脚本使用。
 *
 * 账号矩阵（spec §3.1）:
 *   alice - KB owner + 数据隔离正向验证
 *   bob   - 协作者（read→write→admin 逐级）+ 被降权/移除
 *   carol - 非协作者（隔离对照）+ 并发竞争者 + 被禁用/恢复对象
 *
 * 幂等性: 注册冲突（用户名/邮箱已存在）时直接走登录，脚本可重复执行。
 * 安全: 所有 fetch 带超时（AbortController），无轮询无死循环；账号文件加入 .gitignore。
 *
 * 运行: node deploy/seed_test_accounts.mjs
 */
import { writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BACKEND = 'http://localhost:8000/api/v1';
const OUT_PATH = join(__dirname, 'test_accounts.json');

const PASSWORD = 'TestAcc@2026!rigorous';
const ACCOUNTS = [
  { username: 'alice', email: 'alice.test.rigorous@example.com', role_hint: 'KB owner' },
  { username: 'bob', email: 'bob.test.rigorous@example.com', role_hint: 'collaborator' },
  { username: 'carol', email: 'carol.test.rigorous@example.com', role_hint: 'isolation-control' },
];

/** 带超时的 fetch（防挂起） */
async function api(method, path, body, token) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 15000);
  try {
    const resp = await fetch(`${BACKEND}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    let data = null;
    try { data = await resp.json(); } catch { /* 非 JSON 响应 */ }
    return { status: resp.status, data };
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  console.log('=== T1 测试账号种子 ===');
  const result = { created_at: new Date().toISOString(), password: PASSWORD, accounts: {} };
  let allOk = true;

  for (const acc of ACCOUNTS) {
    // 1. 尝试注册
    const reg = await api('POST', '/auth/register', {
      username: acc.username, email: acc.email, password: PASSWORD,
    });
    let via = null;
    if (reg.status === 200 || reg.status === 201) {
      via = 'register';
      console.log(`  [+] ${acc.username}: 注册成功 (${acc.role_hint})`);
    } else {
      // 只有真正的"用户名/邮箱已存在"冲突才转登录；校验错误(400)等其他情况直接失败
      const msg = String(reg.data?.message || reg.data?.detail || '');
      const isConflict = reg.status === 409 || /已存在|already exist|duplicate/i.test(msg);
      if (isConflict) {
        via = 'existing';
        console.log(`  [~] ${acc.username}: 已存在 (${msg || 'conflict'})，转登录`);
      } else {
        console.error(`  [x] ${acc.username}: 注册失败 ${reg.status} ${msg.substring(0, 200)}`);
        allOk = false;
        continue;
      }
    }

    // 2. 登录拿 token
    const login = await api('POST', '/auth/login', { username: acc.username, password: PASSWORD });
    if (login.status !== 200 || !login.data?.data?.access_token) {
      console.error(`  [x] ${acc.username}: 登录失败 ${login.status} ${JSON.stringify(login.data)?.substring(0, 200)}`);
      allOk = false;
      continue;
    }
    const d = login.data.data;
    const token = d.access_token ?? d.token?.access_token;
    const refresh = d.refresh_token ?? d.token?.refresh_token;

    // 3. /auth/me 验证角色与状态
    const me = await api('GET', '/auth/me', null, token);
    const meData = me.data?.data || {};
    if (me.status !== 200) {
      console.error(`  [x] ${acc.username}: /auth/me 失败 ${me.status}`);
      allOk = false;
      continue;
    }
    if (meData.role !== 'user') {
      console.error(`  [!] ${acc.username}: role=${meData.role}（预期 user）— 记录，可能是历史残留账号`);
    }

    result.accounts[acc.username] = {
      user_id: meData.id,
      username: acc.username,
      email: acc.email,
      role: meData.role,
      is_active: meData.is_active,
      role_hint: acc.role_hint,
      via,
      access_token: token,
      refresh_token: refresh,
      user: meData,
    };
    console.log(`  [✓] ${acc.username}: id=${meData.id} role=${meData.role} active=${meData.is_active} token已获取`);
  }

  if (!allOk) {
    console.error('\n部分账号失败，不写文件。');
    process.exit(1);
  }

  writeFileSync(OUT_PATH, JSON.stringify(result, null, 2));
  console.log(`\n账号文件: ${OUT_PATH}（3 账号就绪）`);
  console.log('注意: 该文件含 token，已在 .gitignore，禁止提交。');
}

main().catch(e => { console.error('致命错误:', e.message); process.exit(1); });

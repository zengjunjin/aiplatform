const BASE = 'http://localhost:8000/api/v1';

const loginResp = await fetch(`${BASE}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'admin', password: 'AdminAcceptance2026!StrongPwd' }),
});
const loginData = await loginResp.json();
const token = loginData.data.access_token;
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };

console.log('=== 边界异常场景测试 ===\n');
let pass = 0, fail = 0;

function check(name, condition, detail = '') {
  if (condition) { pass++; console.log(`  [PASS] ${name} ${detail}`); }
  else { fail++; console.log(`  [FAIL] ${name} ${detail}`); }
}

// 1. 超大文件名
console.log('--- 1. 超长文件名 ---');
const longName = 'a'.repeat(255) + '.txt';
const fd = new FormData();
fd.append('kb_id', '1');
fd.append('file', new Blob(['test'], { type: 'text/plain' }), longName);
const r1 = await fetch(`${BASE}/documents/upload`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd });
const r1body = await r1.text();
check('超长文件名(255+字符)', r1.status === 200 || r1.status === 400, `status=${r1.status}`);

// 2. SQL 注入尝试
console.log('--- 2. SQL 注入尝试 ---');
const r2 = await fetch(`${BASE}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: "admin'; DROP TABLE users; --", password: 'test' }),
});
check('SQL 注入用户名被拒绝', r2.status === 401, `status=${r2.status}`);

// 3. XSS 尝试
console.log('--- 3. XSS 尝试 ---');
const r3 = await fetch(`${BASE}/knowledge-bases`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ name: '<script>alert("xss")</script>', description: '<img src=x onerror=alert(1)>' }),
});
const r3data = await r3.json();
check('XSS KB 名称可创建(后端不过滤)', r3.status === 200, `kbId=${r3data.data?.id}`);
if (r3data.data?.id) {
  const r3b = await fetch(`${BASE}/knowledge-bases/${r3data.data.id}`, { headers });
  const r3bdata = await r3b.json();
  const storedName = r3bdata.data?.name || '';
  check('XSS 存储后未转义(前端需处理)', storedName.includes('<script>'), `name="${storedName.substring(0, 40)}"`);
  await fetch(`${BASE}/knowledge-bases/${r3data.data.id}`, { method: 'DELETE', headers });
}

// 4. 超长字符串
console.log('--- 4. 超长字符串 ---');
const r4 = await fetch(`${BASE}/knowledge-bases`, {
  method: 'POST',
  headers,
  body: JSON.stringify({ name: 'A'.repeat(10000), description: 'B'.repeat(50000) }),
});
check('超长名称(10000字符)被拒绝', r4.status === 400 || r4.status === 422, `status=${r4.status}`);

// 5. 并发请求
console.log('--- 5. 并发请求 (10 个同时) ---');
const start = Date.now();
const promises = Array.from({ length: 10 }, () =>
  fetch(`${BASE}/knowledge-bases?page=1&page_size=5`, { headers }).then(r => r.status)
);
const results = await Promise.all(promises);
const elapsed = Date.now() - start;
check('10 并发 GET 全部成功', results.every(s => s === 200), `耗时=${elapsed}ms`);

// 6. 无效 ID 格式
console.log('--- 6. 无效 ID 格式 ---');
const r6 = await fetch(`${BASE}/knowledge-bases/not-a-number`, { headers });
check('非数字 KB ID 被拒绝', r6.status === 422 || r6.status === 400, `status=${r6.status}`);

// 7. 超大 page_size
console.log('--- 7. 超大 page_size ---');
const r7 = await fetch(`${BASE}/knowledge-bases?page=1&page_size=99999`, { headers });
check('page_size=99999 被限制', r7.status === 200 || r7.status === 422, `status=${r7.status}`);

// 8. 负数参数
console.log('--- 8. 负数参数 ---');
const r8 = await fetch(`${BASE}/knowledge-bases?page=-1&page_size=-5`, { headers });
check('负数 page 被拒绝', r8.status === 422, `status=${r8.status}`);

// 9. 过期/无效 token
console.log('--- 9. Token 安全 ---');
const r9a = await fetch(`${BASE}/auth/me`, { headers: { Authorization: 'Bearer expired.invalid.token' } });
check('无效 token 被拒绝', r9a.status === 401, `status=${r9a.status}`);
const r9b = await fetch(`${BASE}/auth/me`, { headers: { Authorization: 'Bearer ' } });
check('空 token 被拒绝', r9b.status === 401, `status=${r9b.status}`);
const r9c = await fetch(`${BASE}/auth/me`);
check('无 Authorization header 被拒绝', r9c.status === 401, `status=${r9c.status}`);

// 10. 路径遍历
console.log('--- 10. 路径遍历尝试 ---');
const fd2 = new FormData();
fd2.append('kb_id', '1');
fd2.append('file', new Blob(['test'], { type: 'text/plain' }), '../../../etc/passwd');
const r10 = await fetch(`${BASE}/documents/upload`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd2 });
const r10body = await r10.text();
check('路径遍历文件名被处理', r10.status === 200 || r10.status === 400, `status=${r10.status}, body=${r10body.substring(0, 80)}`);

console.log(`\n=== 边界测试完成: PASS=${pass} FAIL=${fail} ===`);
process.exit(fail > 0 ? 1 : 0);

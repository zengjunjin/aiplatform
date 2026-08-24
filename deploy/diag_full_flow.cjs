// 完整闭环验证: alice 建 KB -> 加 bob 协作者 -> 查 DB -> bob 拉列表
const BASE = 'http://localhost:8000/api/v1';
const fs = require('fs');
const { execSync } = require('child_process');
const seed = JSON.parse(fs.readFileSync(__dirname + '/test_accounts.json', 'utf8'));

async function api(method, path, { token, json } = {}) {
  const resp = await fetch(BASE + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: json ? JSON.stringify(json) : undefined,
  });
  const body = await resp.json().catch(() => ({}));
  return { status: resp.status, body };
}

(async () => {
  const kbName = 'diag_full_' + Date.now().toString(36);
  const [aliceR, bobR] = await Promise.all([
    api('POST', '/auth/login', { json: { username: 'alice', password: seed.password } }),
    api('POST', '/auth/login', { json: { username: 'bob', password: seed.password } }),
  ]);
  const alice = aliceR.body.data.access_token;
  const bob = bobR.body.data.access_token;

  // 1. alice 建 KB
  const kbR = await api('POST', '/knowledge-bases', { token: alice, json: { name: kbName, description: 'diag full flow' } });
  const kbId = kbR.body?.data?.id;
  console.log('1. KB 创建:', kbR.status, 'id=', kbId);

  // 2. 加 bob(user_id=3, 已由 KB37 协作者数据验证) 为 read 协作者
  const BOB_ID = 3;
  console.log('2. bob user_id =', BOB_ID);

  const addR = await api('POST', `/knowledge-bases/${kbId}/collaborators`, { token: alice, json: { user_id: BOB_ID, permission: 'read' } });
  console.log('3. 加协作者:', addR.status, JSON.stringify(addR.body?.data));

  // 3. 直接查 DB 确认写入
  const dbOut = execSync(
    `docker exec rag-platform-postgres-1 psql -U rag -d rag_platform -t -c "SELECT collaborators FROM knowledge_bases WHERE id=${kbId}"`,
    { encoding: 'utf8' }
  ).trim();
  console.log('4. DB collaborators =', dbOut);

  // 4. bob 拉列表
  const listR = await api('GET', '/knowledge-bases?page=1&page_size=50', { token: bob });
  const items = listR.body?.data?.items || listR.body?.data || [];
  const names = items.map(k => k.name);
  console.log('5. bob 列表:', names.length, '个:', names.join(', '));
  console.log('\n结论:', names.includes(kbName) ? '✓✓✓ 协作 KB 可见，缺陷完全修复' : '✗ 仍不可见');

  // 清理
  await api('DELETE', `/knowledge-bases/${kbId}`, { token: alice });
  console.log('(已清理)');
})();

// 验证修复: bob 登录拉列表, 检查是否含协作 KB 37 (dbv_mt79v6fe, owner=alice, bob=read)
const BASE = 'http://localhost:8000/api/v1';
const fs = require('fs');
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
  const bob = await api('POST', '/auth/login', { json: { username: 'bob', password: seed.password } });
  if (bob.status !== 200) throw new Error('bob login failed: ' + bob.status);
  const token = bob.body.data.access_token;

  const list = await api('GET', '/knowledge-bases?page=1&page_size=50', { token });
  console.log('list status:', list.status);
  const items = list.body?.data?.items || list.body?.data || [];
  console.log('bob 可见 KB 数:', items.length);
  items.forEach(k => console.log(`  - id=${k.id} name=${k.name} owner=${k.owner_id}`));
  const has37 = items.some(k => k.id === 37 || k.name === 'dbv_mt79v6fe');
  console.log('\n结论: 协作 KB 37', has37 ? '✓ 可见（修复生效）' : '✗ 不可见（仍未生效）');
})();

// 7.3 复现: bob 登录 → alice 建 KB → 加 bob 为 read 协作者 → bob 拉列表验证是否含该 KB
const BASE = 'http://localhost:8000/api/v1';
const fs = require('fs');
const seed = JSON.parse(fs.readFileSync(__dirname + '/test_accounts.json', 'utf8'));

async function api(method, path, { token, json } = {}) {
  const r = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: json ? JSON.stringify(json) : undefined,
  });
  let d = null;
  try { d = await r.json(); } catch {}
  return { status: r.status, d };
}

(async () => {
  const [aliceR, bobR] = await Promise.all([
    api('POST', '/auth/login', { json: { username: 'alice', password: seed.password } }),
    api('POST', '/auth/login', { json: { username: 'bob', password: seed.password } }),
  ]);
  if (aliceR.status !== 200 || bobR.status !== 200) throw new Error('login failed');
  const alice = aliceR.d.data, bob = bobR.d.data;

  const kbName = 'diag73_' + Date.now().toString(36);
  const kb = await api('POST', '/knowledge-bases', { token: alice.access_token, json: { name: kbName } });
  const kbId = kb.d.data.id;
  console.log('kb created:', kbId, kbName);

  const bobId = (await api('GET', '/users/search?q=bob', { token: alice.access_token })).d.data[0].id;

  // 添加前 bob 列表
  const before = await api('GET', '/knowledge-bases?page=1&page_size=100', { token: bob.access_token });
  const namesBefore = before.d.data.items.map(i => i.name);

  const add = await api('POST', `/knowledge-bases/${kbId}/collaborators`, { token: alice.access_token, json: { user_id: bobId, permission: 'read' } });
  console.log('add collab:', add.status);

  // 添加后 bob 列表（两次: 立即 + 2s 后，排除缓存）
  const after1 = await api('GET', '/knowledge-bases?page=1&page_size=100', { token: bob.access_token });
  const namesAfter1 = after1.d.data.items.map(i => i.name);
  await new Promise(r => setTimeout(r, 2000));
  const after2 = await api('GET', '/knowledge-bases?page=1&page_size=100', { token: bob.access_token });
  const namesAfter2 = after2.d.data.items.map(i => i.name);

  console.log('before has kb:', namesBefore.includes(kbName), `(${namesBefore.length} kbs)`);
  console.log('after1 has kb:', namesAfter1.includes(kbName), `(${namesAfter1.length} kbs)`);
  console.log('after2 has kb:', namesAfter2.includes(kbName), `(${namesAfter2.length} kbs)`);

  await api('DELETE', `/knowledge-bases/${kbId}`, { token: alice.access_token });
  console.log('cleaned');
})();

/**
 * 诊断 v2: 完全复刻主测试 1.3 的执行序列 (clearAuth → reload → hash → type → click)
 * 用 v4.1 原版 ToastObserver 脚本 + 完整请求详情 (method/postData)
 * 目的: 判定主测试为何既无 /auth/login 401 也无 toast 捕获
 */
const CDP_HTTP = 'http://127.0.0.1:9223';
const FRONTEND = 'http://tauri.localhost';

let ws, msgId = 1;
const pending = new Map();
const netLog = [];
const navLog = [];

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = msgId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function main() {
  const resp = await fetch(`${CDP_HTTP}/json`);
  const targets = await resp.json();
  const target = targets.find(t => t.type === 'page');
  console.log('target:', target.title, target.url);

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else if (msg.method === 'Network.requestWillBeSent') {
      const req = msg.params.request;
      if (req.url.includes('localhost:8000')) {
        netLog.push({ phase: 'sent', method: req.method, url: req.url.replace('http://localhost:8000', ''), ts: Date.now() });
      }
    } else if (msg.method === 'Network.responseReceived') {
      const r = msg.params.response;
      if (r.url.includes('localhost:8000')) {
        netLog.push({ phase: 'resp', status: r.status, url: r.url.replace('http://localhost:8000', ''), ts: Date.now() });
      }
    } else if (msg.method === 'Page.frameNavigated') {
      const f = msg.params.frame;
      if (!f.parentId) {
        navLog.push({ url: f.url, reason: msg.params.reason || '', ts: Date.now() });
      }
    }
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');

  // ===== v4.1 原版 ToastObserver (从 tauri_cdp_test_v4_ui_coverage.mjs 精确复制) =====
  const observerScript = `
  (() => {
    // 跨文档计数: 每个新文档递增 (检测隐式 reload)
    try {
      const c = parseInt(sessionStorage.getItem('__cdp_doc_count') || '0', 10) + 1;
      sessionStorage.setItem('__cdp_doc_count', String(c));
    } catch (e) {}
    if (window.__cdpToastObserverInstalled) return;
    window.__cdpToastObserverInstalled = true;
    const LOG_KEY = '__cdp_toast_log';

    // ===== sessionStorage 劫持: 记录所有方法调用 (抓 __cdp_toast_log 丢失真凶) =====
    if (!window.__ssHijacked) {
      window.__ssHijacked = true;
      window.__ssLog = [];
      const rec = (op, detail) => {
        try { window.__ssLog.push({ op, val: detail, t: performance.now() }); } catch (e) {}
      };
      const origGet = sessionStorage.getItem.bind(sessionStorage);
      const origSet = sessionStorage.setItem.bind(sessionStorage);
      const origRemove = sessionStorage.removeItem.bind(sessionStorage);
      const origClear = sessionStorage.clear.bind(sessionStorage);
      sessionStorage.getItem = (k) => {
        const v = origGet(k);
        if (k === LOG_KEY) rec('get', (v || 'NULL').substring(0, 120));
        return v;
      };
      sessionStorage.setItem = (k, v) => {
        rec('set:' + k, String(v).substring(0, 120));
        return origSet(k, v);
      };
      sessionStorage.removeItem = (k) => {
        rec('REMOVE_ITEM:' + k, '');
        return origRemove(k);
      };
      sessionStorage.clear = () => {
        rec('*** CLEAR ***', '');
        return origClear();
      };
      // 记录调用栈 (谁在清)
      const origRemove2 = sessionStorage.removeItem;
      sessionStorage.removeItem = function (k) {
        if (k === LOG_KEY) {
          try { throw new Error('trace'); } catch (e) {
            window.__ssLog.push({ op: 'REMOVE_TRACE', val: (e.stack || '').split('\\n').slice(1, 6).join(' <- '), t: performance.now() });
          }
        }
        return origRemove2.call(sessionStorage, k);
      };
    }
    const append = (entry) => {
      try {
        const log = JSON.parse(sessionStorage.getItem(LOG_KEY) || '[]');
        log.push(entry);
        sessionStorage.setItem(LOG_KEY, JSON.stringify(log));
      } catch (e) {
        try { (window.__cdpToastMem = window.__cdpToastMem || []).push(entry); } catch (e2) {}
      }
    };
    const classify = (notice) => {
      const sem = notice.querySelector('[class*="ant-message-error"], [class*="ant-message-success"], [class*="ant-message-warning"], [class*="ant-message-info"], [class*="ant-message-loading"]');
      if (sem) {
        const c = sem.getAttribute('class') || '';
        if (/error/.test(c)) return 'error';
        if (/success/.test(c)) return 'success';
        if (/warning/.test(c)) return 'warning';
        return 'info';
      }
      return 'info';
    };
    const capture = (notice) => {
      const text = (notice.innerText || '').trim().replace(/\\s+/g, ' ');
      if (text) {
        append({ text: text.substring(0, 300), type: classify(notice), ts: Date.now() });
        return;
      }
      requestAnimationFrame(() => {
        try {
          if (!notice.isConnected) return;
          const t2 = (notice.innerText || '').trim().replace(/\\s+/g, ' ');
          if (t2) append({ text: t2.substring(0, 300), type: classify(notice), ts: Date.now() });
        } catch (e) {}
      });
    };
    const noticeSel = '.ant-message-notice, .ant-notification-notice';
    const mo = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches && node.matches(noticeSel)) capture(node);
          else if (node.querySelectorAll) node.querySelectorAll(noticeSel).forEach(capture);
        }
      }
    });
    const start = () => {
      document.querySelectorAll(noticeSel).forEach(capture);
      mo.observe(document.body, { childList: true, subtree: true });
    };
    if (document.body) start();
    else document.addEventListener('DOMContentLoaded', start);
  })();`;

  await send('Page.addScriptToEvaluateOnNewDocument', { source: observerScript });

  // ===== 阶段0: 干净起点 (清 auth + reload) =====
  console.log('\n--- 阶段0: 干净起点 ---');
  await send('Page.navigate', { url: `${FRONTEND}/` });
  await sleep(500);
  await send('Runtime.evaluate', { expression: `localStorage.removeItem('rag-auth'); sessionStorage.removeItem('__cdp_toast_log'); sessionStorage.removeItem('__cdp_doc_count'); true`, returnByValue: true });
  await send('Page.reload');
  await sleep(2000);
  await send('Runtime.evaluate', { expression: `window.location.hash = '#/login'; true`, returnByValue: true });
  await sleep(1500);

  // ===== 阶段1: 复刻 1.2 正确密码登录 (建立 token/refreshToken persist 状态) =====
  console.log('\n--- 阶段1: 复刻 1.2 正确密码登录 ---');
  const setOk = await send('Runtime.evaluate', { expression: `
    (() => {
      const setVal = (sel, val) => {
        const el = document.querySelector(sel);
        if (!el) return { ok: false, error: 'not found: ' + sel };
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { ok: true };
      };
      return {
        r1: setVal('input[id="login_username"], input[name="username"]', 'admin'),
        r2: setVal('input[id="login_password"], input[name="password"]', 'AdminAcceptance2026!StrongPwd'),
      };
    })()`, returnByValue: true });
  console.log('输入结果:', JSON.stringify(setOk.result.value));
  await sleep(300);
  await send('Runtime.evaluate', { expression: `
    (() => {
      let btn = document.querySelector('button[type="submit"]') || document.querySelector('button.ant-btn-primary');
      if (btn) btn.click();
      return true;
    })()`, returnByValue: true });
  await sleep(4000); // 等 dashboard 跳转 + persist 写入
  const afterLogin = await send('Runtime.evaluate', { expression: `(() => ({
    hash: location.hash,
    ragAuth: (localStorage.getItem('rag-auth') || '').substring(0, 200),
    toastLog: sessionStorage.getItem('__cdp_toast_log'),
  }))()`, returnByValue: true });
  console.log('1.2 后状态:', JSON.stringify(afterLogin.result.value, null, 2));

  // ===== 阶段2: 复刻 1.3 clearAuth (与主测试逐行一致) =====
  console.log('\n--- 阶段2: 复刻 clearAuth: navigate → removeItem → reload → hash ---');
  await send('Page.navigate', { url: `${FRONTEND}/` });
  await sleep(500);
  await send('Runtime.evaluate', { expression: `localStorage.removeItem('rag-auth'); true`, returnByValue: true });
  await send('Page.reload');
  await sleep(2000);
  await send('Runtime.evaluate', { expression: `window.location.hash = '#/login'; true`, returnByValue: true });
  await sleep(1500);

  // clearAuth 后立即 dump: 观察 persist 写回竞态 + Dashboard 挂载 toast
  const afterClear = await send('Runtime.evaluate', { expression: `(() => ({
    ragAuth: (localStorage.getItem('rag-auth') || 'EMPTY').substring(0, 250),
    toastLog: sessionStorage.getItem('__cdp_toast_log'),
    hash: location.hash,
  }))()`, returnByValue: true });
  console.log('clearAuth 后状态:', JSON.stringify(afterClear.result.value, null, 2));

  // reload 后 observer 自装检查
  const flag = await send('Runtime.evaluate', { expression: `window.__cdpToastObserverInstalled === true`, returnByValue: true });
  console.log('reload 后 observer 自装:', flag.result.value);
  // 清空遗留日志 (与主测试 clearToastLog 一致)
  await send('Runtime.evaluate', { expression: `sessionStorage.removeItem('__cdp_toast_log'); window.__cdpToastMem = []; true`, returnByValue: true });

  // ===== 复刻 1.3 输入 + 点击 (与主测试逐行一致) =====
  const setR = await send('Runtime.evaluate', { expression: `
    (() => {
      const setVal = (sel, val) => {
        const el = document.querySelector(sel);
        if (!el) return { ok: false, error: 'not found: ' + sel };
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { ok: true, actualValue: el.value };
      };
      return {
        r1: setVal('input[id="login_username"], input[name="username"]', 'admin'),
        r2: setVal('input[id="login_password"], input[name="password"]', 'WrongPassword@2026'),
      };
    })()`, returnByValue: true });
  console.log('输入结果:', JSON.stringify(setR.result.value));
  await sleep(300);

  netLog.length = 0;
  const clickR = await send('Runtime.evaluate', { expression: `
    (() => {
      let btn = document.querySelector('button[type="submit"]') || document.querySelector('button.ant-btn-primary');
      if (btn) btn.click();
      return { clicked: !!btn, btnText: btn ? btn.innerText.trim() : null };
    })()`, returnByValue: true });
  console.log('点击结果:', JSON.stringify(clickR.result.value));

  // ===== 高频采样: 每 400ms 记录日志变化 + 文档计数 (检测隐式 reload) =====
  console.log('\n--- 点击后高频采样 (400ms × 15) ---');
  for (let i = 0; i < 15; i++) {
    await sleep(400);
    const s = await send('Runtime.evaluate', { expression: `(() => ({
      doc: sessionStorage.getItem('__cdp_doc_count'),
      log: sessionStorage.getItem('__cdp_toast_log'),
      href: location.href,
    }))()`, returnByValue: true });
    const v = s.result.value;
    let logSummary = '(空)';
    try {
      const arr = JSON.parse(v.log || '[]');
      logSummary = arr.map(t => `[${t.type}]${t.text}@${t.ts}`).join(' ');
    } catch (e) { logSummary = 'parse错误: ' + (v.log || '').substring(0, 80); }
    console.log(`  ${(i + 1) * 400}ms doc=${v.doc} href=${v.href} log=${logSummary}`);
  }

  const finalState = await send('Runtime.evaluate', { expression: `(() => ({
    observerFlag: window.__cdpToastObserverInstalled === true,
    sessionStorageLog: sessionStorage.getItem('__cdp_toast_log'),
    memLog: window.__cdpToastMem || [],
    hash: location.hash,
    ragAuth: (localStorage.getItem('rag-auth') || 'EMPTY').substring(0, 250),
    ssLog: window.__ssLog || [],
  }))()`, returnByValue: true });
  console.log('\n--- 6 秒后状态 ---');
  console.log('observer 自装:', finalState.result.value.observerFlag);
  console.log('sessionStorage 日志:', finalState.result.value.sessionStorageLog);
  console.log('内存兜底日志:', JSON.stringify(finalState.result.value.memLog));
  console.log('hash:', finalState.result.value.hash);
  console.log('rag-auth:', finalState.result.value.ragAuth);
  console.log('\n--- sessionStorage __cdp_toast_log 读写调用序列 ---');
  (finalState.result.value.ssLog || []).forEach(s => console.log(`  t=${Math.round(s.t)}ms [${s.op}] ${s.val}`));
  if (!(finalState.result.value.ssLog || []).length) console.log('  (无调用记录)');

  console.log('\n--- 全部网络活动 (按时间) ---');
  if (netLog.length === 0) console.log('  (无)');
  const t0 = netLog.length ? netLog[0].ts : 0;
  netLog.forEach(n => console.log(`  +${String(n.ts - t0).padStart(5)}ms [${n.phase}] ${n.status || n.method} ${n.url}`));

  console.log('\n--- 导航事件 (Page.frameNavigated, 主 frame) ---');
  if (navLog.length === 0) console.log('  (无)');
  navLog.forEach(n => console.log(`  ${new Date(n.ts).toLocaleTimeString('zh-CN', { hour12: false })}.${String(n.ts % 1000).padStart(3, '0')} [${n.reason}] ${n.url}`));

  ws.close();
  process.exit(0);
}

main().catch(e => { console.error('诊断失败:', e.message); process.exit(1); });

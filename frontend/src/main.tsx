import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, HashRouter } from 'react-router-dom';
import App from './App';
import { isTauri } from './utils/tauri';
import { reportError } from './utils/errorReporter';
import './i18n';
import './styles/index.css';

// Tauri 环境下使用 HashRouter 避免路由刷新 404 问题
const Router = isTauri() ? HashRouter : BrowserRouter;

// 清理旧版 PWA Service Worker 残留（避免缓存旧版本 JS/CSS）
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((registrations) => {
    registrations.forEach((reg) => reg.unregister());
  });
}

// 全局错误监听：捕获 React 边界之外的运行时错误
window.addEventListener('error', (event) => {
  // event.error 可能不存在（如跨域脚本错误），退化为构造一个 Error
  reportError(event.error || new Error(event.message || 'window.error'));
});

// 捕获未处理的 Promise rejection
window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  const error = reason instanceof Error ? reason : new Error(String(reason));
  reportError(error);
});

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Root element #root not found');

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <Router>
      <App />
    </Router>
  </React.StrictMode>,
);

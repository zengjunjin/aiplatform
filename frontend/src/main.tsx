import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, HashRouter } from 'react-router-dom';
import { ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { isTauri } from './utils/tauri';
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

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN}>
      <AntdApp>
        <Router>
          <App />
        </Router>
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
);

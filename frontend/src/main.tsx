import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, HashRouter } from 'react-router-dom';
import { ConfigProvider, App as AntdApp, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { isTauri } from './utils/tauri';
import './styles/index.css';

const customTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: '#111827',
    colorInfo: '#111827',
    colorSuccess: '#10b981',
    colorWarning: '#f59e0b',
    colorError: '#ef4444',
    borderRadius: 6,
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif',
    fontSize: 14,
    lineHeight: 1.5,
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#fafafa',
      bodyBg: '#f7f7f8',
    },
    Menu: {
      itemBg: 'transparent',
      itemSelectedBg: '#ffffff',
      itemSelectedColor: '#111827',
      itemHoverBg: '#f0f0f0',
      itemHoverColor: '#111827',
      itemColor: '#6b7280',
      itemBorderRadius: 6,
      inlineItemHeight: 40,
    },
    Button: {
      colorPrimary: '#111827',
      colorPrimaryHover: '#1f2937',
      colorPrimaryActive: '#000000',
      algorithm: true,
    },
    Input: {
      hoverBorderColor: '#d1d5db',
      activeBorderColor: '#111827',
      borderRadius: 6,
    },
    Card: {
      borderRadiusLG: 8,
      colorBorderSecondary: '#f0f0f0',
    },
  },
};

// Tauri 环境下使用 HashRouter 避免路由刷新 404 问题
const Router = isTauri() ? HashRouter : BrowserRouter;

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={customTheme}>
      <AntdApp>
        <Router>
          <App />
        </Router>
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
);

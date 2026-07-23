import { Suspense, lazy, useEffect, useState } from 'react';
import type React from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Spin, ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import enUS from 'antd/locale/en_US';
import i18n from './i18n';
import { useAuthStore } from './store/auth';
import ErrorBoundary from './components/ErrorBoundary';
import MainLayout from './components/Layout';
import { addBreadcrumb } from './utils/errorReporter';
import { buildAntdTheme } from './styles/theme';
// 静态导入: 首屏/高频/轻量页面，避免首屏额外的 chunk 请求
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ChatPage from './pages/ChatPage';
import KnowledgeBasesPage from './pages/KnowledgeBasesPage';
import KnowledgeBaseDetailPage from './pages/KnowledgeBaseDetailPage';
import DashboardPage from './pages/DashboardPage';
import NotFoundPage from './pages/NotFoundPage';

// 懒加载页面 (代码分割) - 低频/重资源页面
const SessionsPage = lazy(() => import('./pages/SessionsPage'));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'));
const UsersPage = lazy(() => import('./pages/UsersPage'));
const FeedbackPage = lazy(() => import('./pages/FeedbackPage'));
const EvaluationPage = lazy(() => import('./pages/EvaluationPage'));
const SystemPage = lazy(() => import('./pages/SystemPage'));

const PageLoading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
    <Spin size="large" />
  </div>
);

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  // access_token 仅内存，刷新页面后 token 为 null 但 refreshToken 仍在；
  // 此时允许进入受保护页面，由 onRehydrateStorage / 401 拦截器异步补回 access_token。
  // 若 refreshToken 也无效，refreshAccessToken 失败会触发 logout，AuthWatcher 再跳转登录页。
  if (!token && !refreshToken) return <Navigate to="/login" replace />;
  return <div className="fade-in-page">{children}</div>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.token);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  // 会话有效但 user 尚未加载完成（刷新页面后 access_token 异步补回 / user 异步拉取）时显示 loading，
  // 避免误将管理员重定向到首页
  if (!user) {
    if (token || refreshToken) {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
          <Spin size="large" />
        </div>
      );
    }
    return <Navigate to="/login" replace />;
  }
  if (user.role !== 'admin') return <Navigate to="/" replace />;
  return <>{children}</>;
}

/** 监听 token / refreshToken 变化，登录态失效时自动跳转登录页 */
function AuthWatcher() {
  const token = useAuthStore((s) => s.token);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    const publicPaths = ['/login', '/register'];
    // access_token 与 refreshToken 都为空时，认定为未登录
    if (!token && !refreshToken && !publicPaths.includes(location.pathname)) {
      navigate('/login', { replace: true });
    }
  }, [token, refreshToken, navigate, location.pathname]);
  return null;
}

/** 同步 themeMode 到 document data-theme 属性，供 CSS 变量使用 */
function ThemeSync() {
  const themeMode = useAuthStore((s) => s.themeMode);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', themeMode);
  }, [themeMode]);
  return null;
}

export default function App() {
  const themeMode = useAuthStore((s) => s.themeMode);
  const isDark = themeMode === 'dark';
  const location = useLocation();
  // antd ConfigProvider locale 跟随 i18n 语言动态切换
  const [antdLocale, setAntdLocale] = useState(() =>
    i18n.language === 'en-US' ? enUS : zhCN
  );
  useEffect(() => {
    const handler = (lng: string) => setAntdLocale(lng === 'en-US' ? enUS : zhCN);
    i18n.on('languageChanged', handler);
    return () => {
      i18n.off('languageChanged', handler);
    };
  }, []);

  // 路由变更面包屑：用于错误发生时还原最近 10 条路由跳转
  useEffect(() => {
    addBreadcrumb({ type: 'route', message: location.pathname });
  }, [location.pathname]);

  return (
    <ConfigProvider
      locale={antdLocale}
      theme={buildAntdTheme(isDark)}
    >
      <AntdApp>
        <ErrorBoundary>
          <Suspense fallback={<PageLoading />}>
            <AuthWatcher />
            <ThemeSync />
            <Routes>
            <Route path="/login" element={<ErrorBoundary><LoginPage /></ErrorBoundary>} />
            <Route path="/register" element={<ErrorBoundary><RegisterPage /></ErrorBoundary>} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <MainLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
              <Route path="knowledge-bases" element={<ErrorBoundary><KnowledgeBasesPage /></ErrorBoundary>} />
              <Route path="knowledge-bases/:kbId" element={<ErrorBoundary><KnowledgeBaseDetailPage /></ErrorBoundary>} />
              <Route path="chat" element={<ErrorBoundary><SessionsPage /></ErrorBoundary>} />
              <Route path="chat/:sessionId" element={<ErrorBoundary><ChatPage /></ErrorBoundary>} />
              <Route path="documents" element={<ErrorBoundary><DocumentsPage /></ErrorBoundary>} />
              <Route
                path="users"
                element={
                  <AdminRoute>
                    <ErrorBoundary><UsersPage /></ErrorBoundary>
                  </AdminRoute>
                }
              />
              <Route
                path="feedback"
                element={
                  <AdminRoute>
                    <ErrorBoundary><FeedbackPage /></ErrorBoundary>
                  </AdminRoute>
                }
              />
              <Route
                path="evaluation"
                element={
                  <AdminRoute>
                    <ErrorBoundary><EvaluationPage /></ErrorBoundary>
                  </AdminRoute>
                }
              />
              <Route
                path="system"
                element={
                  <AdminRoute>
                    <ErrorBoundary><SystemPage /></ErrorBoundary>
                  </AdminRoute>
                }
              />
            </Route>
            <Route path="*" element={<ErrorBoundary><NotFoundPage /></ErrorBoundary>} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
      </AntdApp>
    </ConfigProvider>
  );
}

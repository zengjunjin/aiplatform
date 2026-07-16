import { Suspense, lazy, useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import { Spin, ConfigProvider, theme } from 'antd';
import { useAuthStore } from './store/auth';
import ErrorBoundary from './components/ErrorBoundary';
import MainLayout from './components/Layout';

// 懒加载页面 (代码分割)
const LoginPage = lazy(() => import('./pages/LoginPage'));
const RegisterPage = lazy(() => import('./pages/RegisterPage'));
const KnowledgeBasesPage = lazy(() => import('./pages/KnowledgeBasesPage'));
const KnowledgeBaseDetailPage = lazy(() => import('./pages/KnowledgeBaseDetailPage'));
const SessionsPage = lazy(() => import('./pages/SessionsPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'));
const UsersPage = lazy(() => import('./pages/UsersPage'));
const FeedbackPage = lazy(() => import('./pages/FeedbackPage'));
const EvaluationPage = lazy(() => import('./pages/EvaluationPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

const PageLoading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
    <Spin size="large" />
  </div>
);

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <div className="fade-in-page">{children}</div>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user || user.role !== 'admin') return <Navigate to="/" replace />;
  return <>{children}</>;
}

/** 监听 token 变化，401 时自动跳转登录页 */
function AuthWatcher() {
  const token = useAuthStore((s) => s.token);
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    const publicPaths = ['/login', '/register'];
    if (!token && !publicPaths.includes(location.pathname)) {
      navigate('/login', { replace: true });
    }
  }, [token, navigate, location.pathname]);
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

  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: isDark ? '#3b82f6' : '#111827',
          colorInfo: isDark ? '#3b82f6' : '#111827',
          colorSuccess: '#10b981',
          colorWarning: '#f59e0b',
          colorError: '#ef4444',
          borderRadius: 6,
          fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif',
          fontSize: 14,
          lineHeight: 1.5,
          ...(isDark ? {
            colorBgBase: '#0f172a',
            colorBgContainer: '#1e293b',
            colorBgElevated: '#1e293b',
            colorBgLayout: '#0f172a',
            colorBgSpotlight: '#334155',
            colorBorder: '#334155',
            colorBorderSecondary: '#334155',
            colorText: '#f1f5f9',
            colorTextSecondary: '#94a3b8',
            colorTextTertiary: '#64748b',
            colorTextQuaternary: '#475569',
          } : {}),
        },
        components: isDark ? {
          Layout: {
            headerBg: '#1e293b',
            siderBg: '#1e293b',
            bodyBg: '#0f172a',
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: '#334155',
            itemSelectedColor: '#f1f5f9',
            itemHoverBg: '#334155',
            itemHoverColor: '#f1f5f9',
            itemColor: '#94a3b8',
            itemBorderRadius: 6,
          },
          Button: {
            colorPrimary: '#3b82f6',
            colorPrimaryHover: '#2563eb',
            colorPrimaryActive: '#1d4ed8',
            algorithm: true,
          },
          Input: {
            hoverBorderColor: '#475569',
            activeBorderColor: '#3b82f6',
            borderRadius: 6,
          },
          Card: {
            borderRadiusLG: 8,
            colorBorderSecondary: '#334155',
          },
        } : {
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
      }}
    >
      <ErrorBoundary>
        <Suspense fallback={<PageLoading />}>
          <AuthWatcher />
          <ThemeSync />
          <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <MainLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="knowledge-bases" element={<KnowledgeBasesPage />} />
            <Route path="knowledge-bases/:kbId" element={<KnowledgeBaseDetailPage />} />
            <Route path="chat" element={<SessionsPage />} />
            <Route path="chat/:sessionId" element={<ChatPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route
              path="users"
              element={
                <AdminRoute>
                  <UsersPage />
                </AdminRoute>
              }
            />
            <Route
              path="feedback"
              element={
                <AdminRoute>
                  <FeedbackPage />
                </AdminRoute>
              }
            />
            <Route
              path="evaluation"
              element={
                <AdminRoute>
                  <EvaluationPage />
                </AdminRoute>
              }
            />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
    </ConfigProvider>
  );
}

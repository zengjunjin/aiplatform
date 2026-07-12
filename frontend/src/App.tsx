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

  return (
    <ConfigProvider
      theme={{
        algorithm: themeMode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
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

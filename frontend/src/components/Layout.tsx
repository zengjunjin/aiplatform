import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { Layout, Menu, Modal, Form, Input, App as AntdApp, Typography } from 'antd';
import { Outlet, useNavigate, useLocation, NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../store/auth';
import { getErrorMessage, isFormValidationError } from '../utils/errorReporter';
import { debounce } from '../utils/format';
import {
  BookOpen,
  MessageSquare,
  Users,
  LogOut,
  FileText,
  KeyRound,
  Sparkles,
  BarChart3,
  MessageSquareHeart,
  LayoutDashboard,
  Activity,
} from 'lucide-react';
import { isTauri, setWindowTitle } from '../utils/tauri';
import { authApi } from '../api';
import { useWebSocket, WSNotification } from '../hooks/useWebSocket';
import NotificationPopover, { type NotifItem } from './NotificationPopover';
import HeaderActions from './HeaderActions';
import { createPasswordRules } from '../constants/auth';

const { Header, Sider, Content } = Layout;
const { Title, Text } = Typography;

const NOTIF_STORAGE_KEY = 'rag-notifications';

/**
 * Task 36: localStorage 通知列表类型守卫
 * 校验解析结果是否为合法的通知数组 (兼容旧数据: timestamp 可能缺失, 后续 map 会补 0)
 * 仅校验核心字段 type 存在且为 string, 不深入校验 data 子字段, 避免过度校验
 */
function isNotificationList(val: unknown): val is Array<WSNotification | NotifItem> {
  return (
    Array.isArray(val) &&
    val.every(
      (item) =>
        typeof item === 'object' &&
        item !== null &&
        'type' in item &&
        typeof (item as { type: unknown }).type === 'string'
    )
  );
}

export default function MainLayout() {
  const { t, i18n } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const themeMode = useAuthStore((s) => s.themeMode);
  const toggleTheme = useAuthStore((s) => s.toggleTheme);
  const navigate = useNavigate();
  const location = useLocation();
  const [pwdModal, setPwdModal] = useState(false);
  const [pwdForm] = Form.useForm();
  const { message } = AntdApp.useApp();

  // WebSocket 通知
  const [notifications, setNotifications] = useState<NotifItem[]>(() => {
    try {
      const stored = localStorage.getItem(NOTIF_STORAGE_KEY);
      if (!stored) return [];
      const parsed: unknown = JSON.parse(stored);
      // Task 36: 类型守卫校验, 不合法则回退空数组, 避免脏数据导致后续 push/render 抛错
      if (!isNotificationList(parsed)) return [];
      // 兼容旧数据: 没有 timestamp 字段的旧通知补 0 (视为已读)
      return parsed.map((n) => ({
        ...(n as WSNotification),
        timestamp: typeof (n as NotifItem).timestamp === 'number' ? (n as NotifItem).timestamp : 0,
      }));
    } catch {
      return [];
    }
  });
  const [notifPopoverOpen, setNotifPopoverOpen] = useState(false);
  // 用户上次打开通知 Popover 的时间戳, 之后到达的通知才算未读
  const [readAt, setReadAt] = useState(0);

  const token = useAuthStore((s) => s.token);

  // Task 18 (P1-FE-04): 高频 WS 通知 debounce 批量处理, 避免每条通知都触发 setState + localStorage
  // 暂存期间通知累积在 ref 中, 300ms 内无新通知则 flush 到 state
  const pendingNotificationsRef = useRef<NotifItem[]>([]);

  const flushPendingNotifications = useCallback(() => {
    const pending = pendingNotificationsRef.current;
    if (pending.length === 0) return;
    pendingNotificationsRef.current = [];
    // push 顺序为旧→新, 反转后新→旧, 与原 [item, ...prev] 顺序一致
    const newItems = pending.slice().reverse();
    setNotifications((prev) => {
      const updated = [...newItems, ...prev].slice(0, 50);
      localStorage.setItem(NOTIF_STORAGE_KEY, JSON.stringify(updated));
      return updated;
    });
  }, []);

  const debouncedFlushNotifications = useMemo(
    () => debounce(flushPendingNotifications, 300),
    [flushPendingNotifications]
  );

  const handleWebSocketMessage = useCallback((data: WSNotification) => {
    // 客户端附加 timestamp 用于未读数过滤 (后端 WSNotification 无 timestamp 字段)
    const item: NotifItem = { ...data, timestamp: Date.now() };
    pendingNotificationsRef.current.push(item);
    debouncedFlushNotifications();
    // 修复运算符优先级: 原代码 data.type + x?.doc_id || Date.now() 中 + 优先级高于 ||
    // 导致 Date.now() 分支永远不可达（字符串拼接结果恒为 truthy）
    // WSNotification.data 为 Record<string, unknown>, 用类型守卫提取 doc_id
    const dataData = data.data;
    const docId = dataData && typeof dataData === 'object' && 'doc_id' in dataData
      ? (dataData as { doc_id: number | string }).doc_id
      : undefined;
    const notifKey = docId != null ? `${data.type}-${docId}` : `${data.type}-${Date.now()}`;
    message.info({
      content: data.message || data.title || t('notification.default', { type: data.type }),
      key: notifKey,
    });
  }, [message, t, debouncedFlushNotifications]);

  useWebSocket(token, handleWebSocketMessage);

  // 卸载时取消 pending debounce, 避免在已卸载组件上 setState
  useEffect(() => {
    return () => {
      debouncedFlushNotifications.cancel();
    };
  }, [debouncedFlushNotifications]);

  const handleLogout = useCallback(async () => {
    await logout();
    navigate('/login');
  }, [logout, navigate]);

  const handleChangePwd = useCallback(async () => {
    try {
      const values = await pwdForm.validateFields();
      await authApi.changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
        confirm_password: values.confirm_password,
      });
      message.success(t('auth.changePasswordSuccess'));
      setPwdModal(false);
      pwdForm.resetFields();
      logout();
      navigate('/login');
    } catch (e: unknown) {
      if (isFormValidationError(e)) return;
      message.error(getErrorMessage(e) || t('auth.changePasswordFailed'));
    }
  }, [pwdForm, message, t, logout, navigate]);

  const toggleLanguage = useCallback(() => {
    const newLang = i18n.language === 'zh-CN' ? 'en-US' : 'zh-CN';
    i18n.changeLanguage(newLang);
    localStorage.setItem('i18n-lang', newLang);
  }, [i18n]);

  const menuItems = useMemo(() => [
    {
      key: '/dashboard',
      icon: <LayoutDashboard size={18} strokeWidth={1.8} />,
      label: <NavLink to="/dashboard">{t('nav.dashboard')}</NavLink>,
    },
    {
      key: '/chat',
      icon: <MessageSquare size={18} strokeWidth={1.8} />,
      label: <NavLink to="/chat">{t('nav.chat')}</NavLink>,
    },
    {
      key: '/knowledge-bases',
      icon: <BookOpen size={18} strokeWidth={1.8} />,
      label: <NavLink to="/knowledge-bases">{t('nav.knowledgeBase')}</NavLink>,
    },
    {
      key: '/documents',
      icon: <FileText size={18} strokeWidth={1.8} />,
      label: <NavLink to="/documents">{t('nav.documents')}</NavLink>,
    },
    ...(user?.role === 'admin'
      ? [
          {
            key: '/users',
            icon: <Users size={18} strokeWidth={1.8} />,
            label: <NavLink to="/users">{t('nav.userManagement')}</NavLink>,
          },
          {
            key: '/feedback',
            icon: <MessageSquareHeart size={18} strokeWidth={1.8} />,
            label: <NavLink to="/feedback">{t('nav.feedback')}</NavLink>,
          },
          {
            key: '/evaluation',
            icon: <BarChart3 size={18} strokeWidth={1.8} />,
            label: <NavLink to="/evaluation">{t('nav.evaluation')}</NavLink>,
          },
          {
            key: '/system',
            icon: <Activity size={18} strokeWidth={1.8} />,
            label: <NavLink to="/system">{t('nav.system')}</NavLink>,
          },
        ]
      : []),
  ], [t, user?.role]);

  const userMenuItems = useMemo(() => [
    {
      key: 'password',
      icon: <KeyRound size={16} strokeWidth={1.8} />,
      label: t('nav.changePassword'),
      onClick: () => setPwdModal(true),
    },
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogOut size={16} strokeWidth={1.8} />,
      label: t('nav.logout'),
      onClick: handleLogout,
    },
  ], [t, handleLogout]);

  const selectedKey = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith('/dashboard')) return '/dashboard';
    if (path.startsWith('/chat')) return '/chat';
    if (path.startsWith('/knowledge-bases')) return '/knowledge-bases';
    if (path.startsWith('/documents')) return '/documents';
    if (path.startsWith('/users')) return '/users';
    if (path.startsWith('/feedback')) return '/feedback';
    if (path.startsWith('/evaluation')) return '/evaluation';
    if (path.startsWith('/system')) return '/system';
    return '/dashboard';
  }, [location.pathname]);

  const pageTitle = useMemo(() => {
    switch (selectedKey) {
      case '/dashboard': return t('nav.dashboard');
      case '/chat': return t('nav.chat');
      case '/knowledge-bases': return t('nav.knowledgeBase');
      case '/documents': return t('nav.documents');
      case '/users': return t('nav.userManagement');
      case '/system': return t('nav.system');
      default: return t('nav.dashboard');
    }
  }, [selectedKey, t]);

  useEffect(() => {
    if (isTauri()) setWindowTitle(t('common.platformWindowTitle'));
  }, [t]);

  // Task 54: 全局错误 toasts - 监听 window error 与 unhandledrejection 事件
  // ErrorBoundary 已捕获的渲染错误不会冒泡到 window, 此处仅捕获事件回调 / 定时器 / Promise 等未捕获错误
  useEffect(() => {
    const handleError = (event: ErrorEvent) => {
      const msg = event.message || t('errorBoundary.globalErrorToast');
      message.error(msg, 5);
    };
    const handleRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      const msg = reason instanceof Error
        ? reason.message
        : (typeof reason === 'string' ? reason : t('errorBoundary.unhandledRejectionToast'));
      message.error(msg, 5);
    };
    window.addEventListener('error', handleError);
    window.addEventListener('unhandledrejection', handleRejection);
    return () => {
      window.removeEventListener('error', handleError);
      window.removeEventListener('unhandledrejection', handleRejection);
    };
  }, [message, t]);

  // Task 47: 离线状态检测与提示
  useEffect(() => {
    const handleOffline = () => {
      message.warning(t('common.offlineWarning'));
    };
    const handleOnline = () => {
      message.success(t('common.backOnline'));
    };
    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, [message, t]);

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <a href="#main-content" className="skip-link">{t('common.skipToMainContent')}</a>
      <Sider
        width={240}
        breakpoint="lg"
        collapsedWidth={0}
        style={{
          background: 'var(--bg-secondary)',
          borderRight: '1px solid var(--border-color)',
          transition: 'all var(--transition-slow)',
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            padding: '0 20px',
            gap: 12,
            borderBottom: '1px solid var(--border-color)',
          }}
        >
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)',
              backgroundSize: '200% 200%',
              animation: 'logoGradient 4s ease infinite',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 12px rgba(102, 126, 234, 0.3)',
            }}
          >
            <Sparkles size={20} color="#ffffff" strokeWidth={1.8} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <Text strong style={{ fontSize: 15, color: 'var(--text-primary)', lineHeight: 1.2, letterSpacing: '0.5px' }}>
              {t('nav.platformName')}
            </Text>
            <Text style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.2, letterSpacing: '0.3px' }}>
              {t('nav.platformSubtitle')}
            </Text>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          style={{
            borderRight: 0,
            padding: '12px 12px',
            background: 'transparent',
          }}
          items={menuItems}
        />
      </Sider>
      <Layout style={{ background: 'var(--bg-primary)' }}>
        <Header
          style={{
            padding: '0 32px',
            background: 'var(--bg-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid var(--border-color)',
            height: 64,
            lineHeight: '64px',
          }}
        >
          <div>
            <Title level={5} style={{ margin: 0, color: 'var(--text-primary)', fontWeight: 600 }}>
              {pageTitle}
            </Title>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <NotificationPopover
              open={notifPopoverOpen}
              notifications={notifications}
              readAt={readAt}
              onOpenChange={(open) => {
                setNotifPopoverOpen(open);
                // 打开 Popover 即视为已读, 清零未读计数
                if (open) setReadAt(Date.now());
              }}
              onClear={() => {
                pendingNotificationsRef.current = [];
                debouncedFlushNotifications.cancel();
                setNotifications([]);
                localStorage.removeItem(NOTIF_STORAGE_KEY);
              }}
            />
            <HeaderActions
              user={user}
              themeMode={themeMode}
              currentLang={i18n.language}
              userMenuItems={userMenuItems}
              onToggleLanguage={toggleLanguage}
              onToggleTheme={toggleTheme}
            />
          </div>
        </Header>
        <Content id="main-content" tabIndex={-1} style={{ padding: '24px 32px', outline: 'none' }}>
          <Outlet />
        </Content>
      </Layout>

      <Modal
        title={t('auth.changePasswordTitle')}
        open={pwdModal}
        onOk={handleChangePwd}
        onCancel={() => {
          setPwdModal(false);
          pwdForm.resetFields();
        }}
        transitionName=""
        maskTransitionName=""
        okText={t('auth.changePasswordConfirm')}
        cancelText={t('common.cancel')}
        centered
      >
        <Form form={pwdForm} layout="vertical">
          <Form.Item
            name="old_password"
            label={t('auth.currentPassword')}
            rules={[{ required: true, message: t('auth.currentPasswordRequired') }]}
          >
            <Input.Password placeholder={t('auth.currentPasswordPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="new_password"
            label={t('auth.newPassword')}
            rules={createPasswordRules(t)}
          >
            <Input.Password placeholder={t('auth.newPasswordPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label={t('auth.confirmNewPassword')}
            dependencies={['new_password']}
            rules={[
              { required: true, message: t('auth.confirmNewPasswordRequired') },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t('auth.passwordMismatch')));
                },
              }),
            ]}
          >
            <Input.Password placeholder={t('auth.confirmNewPasswordPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}

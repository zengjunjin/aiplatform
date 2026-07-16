import { useEffect, useState, useCallback } from 'react';
import { Layout, Menu, Avatar, Dropdown, Button, Modal, Form, Input, App as AntdApp, Typography, Badge, List, Popover } from 'antd';
import { Outlet, useNavigate, useLocation, NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../store/auth';
import {
  BookOpen,
  MessageSquare,
  Users,
  LogOut,
  Database,
  FileText,
  KeyRound,
  Sparkles,
  Sun,
  Moon,
  Languages,
  BarChart3,
  MessageSquareHeart,
  Bell,
} from 'lucide-react';
import { isTauri, setWindowTitle } from '../utils/tauri';
import { authApi } from '../api';
import { useWebSocket, WSNotification } from '../hooks/useWebSocket';

const { Header, Sider, Content } = Layout;
const { Title, Text } = Typography;

const NOTIF_STORAGE_KEY = 'rag-notifications';

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
  const [notifications, setNotifications] = useState<WSNotification[]>(() => {
    try {
      const stored = localStorage.getItem(NOTIF_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [notifPopoverOpen, setNotifPopoverOpen] = useState(false);

  const token = useAuthStore((s) => s.token);

  const handleWebSocketMessage = useCallback((data: WSNotification) => {
    setNotifications((prev) => {
      const updated = [data, ...prev].slice(0, 50);
      localStorage.setItem(NOTIF_STORAGE_KEY, JSON.stringify(updated));
      return updated;
    });
    // 修复运算符优先级: 原代码 data.type + x?.doc_id || Date.now() 中 + 优先级高于 ||
    // 导致 Date.now() 分支永远不可达（字符串拼接结果恒为 truthy）
    const docId = (data.data as any)?.doc_id;
    const notifKey = docId != null ? `${data.type}-${docId}` : `${data.type}-${Date.now()}`;
    message.info({
      content: data.message || data.title || `通知: ${data.type}`,
      key: notifKey,
    });
  }, [message]);

  useWebSocket(token, handleWebSocketMessage);

  const unreadCount = notifications.length;

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const handleChangePwd = async () => {
    try {
      const values = await pwdForm.validateFields();
      await authApi.changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      });
      message.success(t('auth.changePasswordSuccess'));
      setPwdModal(false);
      pwdForm.resetFields();
      logout();
      navigate('/login');
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || t('auth.changePasswordFailed'));
    }
  };

  const toggleLanguage = () => {
    const newLang = i18n.language === 'zh-CN' ? 'en-US' : 'zh-CN';
    i18n.changeLanguage(newLang);
    localStorage.setItem('i18n-lang', newLang);
  };

  const menuItems = [
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
        ]
      : []),
  ];

  const userMenuItems = [
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
  ];

  const getSelectedKey = () => {
    const path = location.pathname;
    if (path.startsWith('/chat')) return '/chat';
    if (path.startsWith('/knowledge-bases')) return '/knowledge-bases';
    if (path.startsWith('/documents')) return '/documents';
    if (path.startsWith('/users')) return '/users';
    if (path.startsWith('/feedback')) return '/feedback';
    if (path.startsWith('/evaluation')) return '/evaluation';
    return '/chat';
  };

  const getPageTitle = () => {
    const key = getSelectedKey();
    switch (key) {
      case '/chat': return t('nav.chat');
      case '/knowledge-bases': return t('nav.knowledgeBase');
      case '/documents': return t('nav.documents');
      case '/users': return t('nav.userManagement');
      default: return t('nav.chat');
    }
  };

  useEffect(() => {
    if (isTauri()) setWindowTitle(t('common.platformWindowTitle'));
  }, [t]);

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
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
          selectedKeys={[getSelectedKey()]}
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
              {getPageTitle()}
            </Title>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Popover
              open={notifPopoverOpen}
              onOpenChange={setNotifPopoverOpen}
              trigger="click"
              placement="bottomRight"
              title="通知"
              content={
                <div style={{ width: 320, maxHeight: 360, overflow: 'auto' }}>
                  {notifications.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-secondary)' }}>
                      暂无通知
                    </div>
                  ) : (
                    <List
                      dataSource={notifications}
                      renderItem={(item, index) => (
                        <List.Item
                          key={index}
                          style={{ padding: '8px 0', borderBottom: '1px solid var(--border-color)' }}
                        >
                          <List.Item.Meta
                            title={<Text strong style={{ fontSize: 13 }}>{item.title || item.type}</Text>}
                            description={
                              <Text style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                {item.message || JSON.stringify(item.data)}
                              </Text>
                            }
                          />
                        </List.Item>
                      )}
                    />
                  )}
                  {notifications.length > 0 && (
                    <div style={{ textAlign: 'center', paddingTop: 8 }}>
                      <Button
                        type="link"
                        size="small"
                        onClick={() => { setNotifications([]); localStorage.removeItem(NOTIF_STORAGE_KEY); }}
                      >
                        清空通知
                      </Button>
                    </div>
                  )}
                </div>
              }
            >
              <Badge count={unreadCount} size="small" overflowCount={99}>
                <Button
                  type="text"
                  icon={<Bell size={18} strokeWidth={1.8} />}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                />
              </Badge>
            </Popover>
            <Button
              type="text"
              icon={<Languages size={18} strokeWidth={1.8} />}
              onClick={toggleLanguage}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, fontSize: 12 }}
            >
              {i18n.language === 'zh-CN' ? 'EN' : '中'}
            </Button>
            <Button
              type="text"
              icon={themeMode === 'dark' ? <Sun size={18} strokeWidth={1.8} /> : <Moon size={18} strokeWidth={1.8} />}
              onClick={toggleTheme}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            />
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <div
              style={{
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 12px',
                borderRadius: 8,
                transition: 'background 0.15s ease',
              }}
              className="user-dropdown-trigger"
            >
              <Avatar
                size={32}
                style={{
                  backgroundColor: 'var(--bg-secondary)',
                  color: 'var(--text-primary)',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {user?.username?.charAt(0)?.toUpperCase()}
              </Avatar>
              <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <Text style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500 }}>
                  {user?.username}
                </Text>
                <Text style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  {user?.role === 'admin' ? t('user.admin') : t('user.normalUser')}
                </Text>
              </div>
            </div>
          </Dropdown>
          </div>
        </Header>
        <Content style={{ padding: '24px 32px' }}>
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
            rules={[
              { required: true, message: t('auth.newPasswordRequired') },
              { min: 6, message: t('auth.newPasswordMinLength') },
            ]}
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

      <style>{`
        .user-dropdown-trigger:hover {
          background: var(--bg-hover);
        }
        .ant-menu-item {
          margin-bottom: 2px !important;
          border-radius: var(--radius-md) !important;
          transition: all var(--transition-base) !important;
          border-left: 3px solid transparent !important;
          padding-left: 21px !important;
        }
        .ant-menu-item:hover {
          background: var(--bg-tertiary) !important;
        }
        .ant-menu-item-selected {
          background: var(--bg-tertiary) !important;
          box-shadow: var(--shadow-sm) !important;
          border-left: 3px solid var(--accent-primary) !important;
          padding-left: 21px !important;
        }
        @keyframes logoGradient {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
      `}</style>
    </Layout>
  );
}

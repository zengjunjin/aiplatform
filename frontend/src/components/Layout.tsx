import { useEffect, useState } from 'react';
import { Layout, Menu, Avatar, Dropdown, Button, Modal, Form, Input, App as AntdApp, Typography } from 'antd';
import { Outlet, useNavigate, useLocation, NavLink } from 'react-router-dom';
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
} from 'lucide-react';
import { isTauri, setWindowTitle } from '../utils/tauri';
import { authApi } from '../api';

const { Header, Sider, Content } = Layout;
const { Title, Text } = Typography;

export default function MainLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const location = useLocation();
  const [pwdModal, setPwdModal] = useState(false);
  const [pwdForm] = Form.useForm();
  const { message } = AntdApp.useApp();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleChangePwd = async () => {
    try {
      const values = await pwdForm.validateFields();
      await authApi.changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      });
      message.success('密码修改成功，请重新登录');
      setPwdModal(false);
      pwdForm.resetFields();
      logout();
      navigate('/login');
    } catch (e: any) {
      if (e.errorFields) return;
      message.error(e.message || '修改失败');
    }
  };

  const menuItems = [
    {
      key: '/chat',
      icon: <MessageSquare size={18} strokeWidth={1.8} />,
      label: <NavLink to="/chat">对话</NavLink>,
    },
    {
      key: '/knowledge-bases',
      icon: <BookOpen size={18} strokeWidth={1.8} />,
      label: <NavLink to="/knowledge-bases">知识库</NavLink>,
    },
    {
      key: '/documents',
      icon: <FileText size={18} strokeWidth={1.8} />,
      label: <NavLink to="/documents">文档管理</NavLink>,
    },
    ...(user?.role === 'admin'
      ? [
          {
            key: '/users',
            icon: <Users size={18} strokeWidth={1.8} />,
            label: <NavLink to="/users">用户管理</NavLink>,
          },
        ]
      : []),
  ];

  const userMenuItems = [
    {
      key: 'password',
      icon: <KeyRound size={16} strokeWidth={1.8} />,
      label: '修改密码',
      onClick: () => setPwdModal(true),
    },
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogOut size={16} strokeWidth={1.8} />,
      label: '退出登录',
      onClick: handleLogout,
    },
  ];

  const getSelectedKey = () => {
    const path = location.pathname;
    if (path.startsWith('/chat')) return '/chat';
    if (path.startsWith('/knowledge-bases')) return '/knowledge-bases';
    if (path.startsWith('/documents')) return '/documents';
    if (path.startsWith('/users')) return '/users';
    return '/chat';
  };

  useEffect(() => {
    if (isTauri()) setWindowTitle('RAG 知识库平台');
  }, []);

  return (
    <Layout style={{ minHeight: '100vh', background: '#f7f7f8' }}>
      <Sider
        width={240}
        breakpoint="lg"
        collapsedWidth={0}
        style={{
          background: '#fafafa',
          borderRight: '1px solid #f0f0f0',
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            padding: '0 20px',
            gap: 12,
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #111827 0%, #374151 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Sparkles size={18} color="#ffffff" strokeWidth={1.8} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <Text strong style={{ fontSize: 15, color: '#111827', lineHeight: 1.2 }}>
              RAG Platform
            </Text>
            <Text style={{ fontSize: 11, color: '#9ca3af', lineHeight: 1.2 }}>
              Knowledge Base
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
      <Layout style={{ background: '#f7f7f8' }}>
        <Header
          style={{
            padding: '0 32px',
            background: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
            height: 64,
            lineHeight: '64px',
          }}
        >
          <div>
            <Title level={5} style={{ margin: 0, color: '#111827', fontWeight: 600 }}>
              {getSelectedKey() === '/chat' && '对话'}
              {getSelectedKey() === '/knowledge-bases' && '知识库'}
              {getSelectedKey() === '/documents' && '文档管理'}
              {getSelectedKey() === '/users' && '用户管理'}
            </Title>
          </div>
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
                  backgroundColor: '#f3f4f6',
                  color: '#111827',
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {user?.username?.charAt(0)?.toUpperCase()}
              </Avatar>
              <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <Text style={{ fontSize: 13, color: '#111827', fontWeight: 500 }}>
                  {user?.username}
                </Text>
                <Text style={{ fontSize: 11, color: '#9ca3af' }}>
                  {user?.role === 'admin' ? '管理员' : '用户'}
                </Text>
              </div>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ padding: '24px 32px' }}>
          <Outlet />
        </Content>
      </Layout>

      <Modal
        title="修改密码"
        open={pwdModal}
        onOk={handleChangePwd}
        onCancel={() => {
          setPwdModal(false);
          pwdForm.resetFields();
        }}
        okText="确认修改"
        cancelText="取消"
        centered
      >
        <Form form={pwdForm} layout="vertical">
          <Form.Item
            name="old_password"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password placeholder="请输入当前密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password placeholder="请输入新密码（至少 6 位）" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>

      <style>{`
        .user-dropdown-trigger:hover {
          background: #f9fafb;
        }
        .ant-menu-item {
          margin-bottom: 2px !important;
        }
        .ant-menu-item-selected {
          box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }
      `}</style>
    </Layout>
  );
}

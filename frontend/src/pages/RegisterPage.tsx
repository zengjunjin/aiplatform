import { Form, Input, Button, Typography, App as AntdApp } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import { useState } from 'react';
import { Sparkles } from 'lucide-react';

const { Title, Text } = Typography;

export default function RegisterPage() {
  const [loading, setLoading] = useState(false);
  const register = useAuthStore((s) => s.register);
  const navigate = useNavigate();
  const { message: msg } = AntdApp.useApp();

  const onFinish = async (values: { username: string; email: string; password: string; confirm: string }) => {
    if (values.password !== values.confirm) {
      msg.error('两次输入的密码不一致');
      return;
    }
    setLoading(true);
    try {
      await register(values.username, values.email, values.password);
      msg.success('注册成功');
      navigate('/');
    } catch (e: any) {
      msg.error(e.message || '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f7f7f8',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '-20%',
          right: '-10%',
          width: 600,
          height: 600,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(17,24,39,0.04) 0%, rgba(17,24,39,0) 70%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '-20%',
          left: '-10%',
          width: 500,
          height: 500,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(17,24,39,0.03) 0%, rgba(17,24,39,0) 70%)',
        }}
      />

      <div
        style={{
          width: 420,
          position: 'relative',
          zIndex: 1,
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 14,
              background: 'linear-gradient(135deg, #111827 0%, #374151 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 20px',
              boxShadow: '0 8px 24px rgba(17,24,39,0.15)',
            }}
          >
            <Sparkles size={28} color="#ffffff" strokeWidth={1.8} />
          </div>
          <Title level={3} style={{ marginBottom: 8, fontWeight: 700, color: '#111827' }}>
            创建账户
          </Title>
          <Text style={{ color: '#6b7280', fontSize: 14 }}>
            开始使用 RAG 智能知识库
          </Text>
        </div>

        <div
          style={{
            background: '#ffffff',
            borderRadius: 12,
            padding: 32,
            boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)',
            border: '1px solid #f0f0f0',
          }}
        >
          <Form
            name="register"
            onFinish={onFinish}
            autoComplete="off"
            layout="vertical"
          >
            <Form.Item
              name="username"
              label="用户名"
              rules={[
                { required: true, message: '请输入用户名' },
                { min: 3, message: '用户名至少 3 个字符' },
              ]}
            >
              <Input placeholder="请输入用户名" size="large" />
            </Form.Item>
            <Form.Item
              name="email"
              label="邮箱"
              rules={[
                { required: true, message: '请输入邮箱' },
                { type: 'email', message: '请输入有效的邮箱地址' },
              ]}
            >
              <Input placeholder="请输入邮箱" size="large" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 8, message: '密码至少 8 个字符' },
                {
                  pattern: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\/]).+$/,
                  message: '密码需包含大写字母、小写字母、数字和特殊字符',
                },
              ]}
            >
              <Input.Password placeholder="请输入密码" size="large" />
            </Form.Item>
            <Form.Item
              name="confirm"
              label="确认密码"
              rules={[{ required: true, message: '请确认密码' }]}
            >
              <Input.Password placeholder="请再次输入密码" size="large" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 20, marginTop: 8 }}>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                size="large"
                style={{
                  height: 44,
                  fontWeight: 500,
                }}
              >
                注册
              </Button>
            </Form.Item>
            <div style={{ textAlign: 'center' }}>
              <Text style={{ color: '#6b7280', fontSize: 13 }}>
                已有账户？{' '}
                <Button
                  type="link"
                  onClick={() => navigate('/login')}
                  style={{
                    color: '#111827',
                    fontWeight: 500,
                    padding: 0,
                    height: 'auto',
                    borderBottom: '1px solid #d1d5db',
                    borderRadius: 0,
                  }}
                >
                  立即登录
                </Button>
              </Text>
            </div>
          </Form>
        </div>

        <div style={{ textAlign: 'center', marginTop: 32 }}>
          <Text style={{ color: '#9ca3af', fontSize: 12 }}>
            © 2026 RAG Platform · 智能知识库系统
          </Text>
        </div>
      </div>
    </div>
  );
}

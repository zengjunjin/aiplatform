import { Form, Input, Button, Typography, App as AntdApp } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';

const { Title, Text } = Typography;

export default function LoginPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();
  const { message: msg } = AntdApp.useApp();

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login(values.username, values.password);
      msg.success(t('auth.loginSuccess'));
      navigate('/');
    } catch (e: any) {
      msg.error(e.message || t('auth.loginFailed'));
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
          width: 400,
          position: 'relative',
          zIndex: 1,
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
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
            {t('auth.welcomeBack')}
          </Title>
          <Text style={{ color: '#6b7280', fontSize: 14 }}>
            {t('auth.loginSubtitle')}
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
            name="login"
            onFinish={onFinish}
            autoComplete="off"
            layout="vertical"
          >
            <Form.Item
              name="username"
              label={t('auth.username')}
              rules={[{ required: true, message: t('auth.usernameRequired') }]}
            >
              <Input placeholder={t('auth.usernamePlaceholder')} size="large" />
            </Form.Item>
            <Form.Item
              name="password"
              label={t('auth.password')}
              rules={[{ required: true, message: t('auth.passwordRequired') }]}
            >
              <Input.Password placeholder={t('auth.passwordPlaceholder')} size="large" />
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
                {t('auth.login')}
              </Button>
            </Form.Item>
            <div style={{ textAlign: 'center' }}>
                <span style={{ color: '#6b7280', fontSize: 13 }}>
                  {t('auth.noAccount')}{' '}
                  <Button
                    type="text"
                    onClick={() => navigate('/register')}
                    style={{
                      color: '#111827',
                      fontWeight: 500,
                      padding: 0,
                      height: 'auto',
                      borderBottom: '1px solid #d1d5db',
                      borderRadius: 0,
                    }}
                  >
                    {t('auth.registerNow')}
                  </Button>
                </span>
              </div>
          </Form>
        </div>

        <div style={{ textAlign: 'center', marginTop: 32 }}>
          <Text style={{ color: '#9ca3af', fontSize: 12 }}>
            {t('auth.copyright')}
          </Text>
        </div>
      </div>
    </div>
  );
}

import { Form, Input, Button, Typography, App as AntdApp, Tooltip } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { getErrorMessage } from '../utils/errorReporter';
import { createPasswordRules } from '../constants/auth';

const { Title, Text } = Typography;

/**
 * Task 55: 密码强度可视化组件
 * 5 段分别对应：长度 / 大写字母 / 小写字母 / 数字 / 特殊字符
 * 每段满足时高亮（绿），未满足时灰显
 */
function PasswordStrengthBar({ value }: { value: string }) {
  const { t } = useTranslation();
  const checks = useMemo(() => {
    return [
      { key: 'length', label: t('auth.passwordStrength.length'), met: value.length >= 8 },
      { key: 'uppercase', label: t('auth.passwordStrength.uppercase'), met: /[A-Z]/.test(value) },
      { key: 'lowercase', label: t('auth.passwordStrength.lowercase'), met: /[a-z]/.test(value) },
      { key: 'digit', label: t('auth.passwordStrength.digit'), met: /\d/.test(value) },
      { key: 'symbol', label: t('auth.passwordStrength.symbol'), met: /[!@#$%^&*(),.?":{}|<>_\-+=[\]\\/]/.test(value) },
    ];
  }, [value, t]);

  const allMet = checks.every((c) => c.met);

  return (
    <div style={{ marginTop: 8 }} aria-label={t('auth.passwordStrength.title')}>
      {/* 5 段强度条 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
        {checks.map((c) => (
          <Tooltip key={c.key} title={c.label}>
            <div
              style={{
                flex: 1,
                height: 4,
                borderRadius: 2,
                background: c.met ? 'var(--accent-success)' : 'var(--bg-hover)',
                transition: 'background var(--transition-fast)',
              }}
            />
          </Tooltip>
        ))}
      </div>
      {/* 标签列表 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {checks.map((c) => (
          <Text
            key={c.key}
            style={{
              fontSize: 11,
              color: c.met ? 'var(--accent-success)' : 'var(--text-tertiary)',
              transition: 'color var(--transition-fast)',
            }}
          >
            {c.met ? '✓ ' : '○ '}
            {c.label}
          </Text>
        ))}
      </div>
      {value && (
        <Text
          style={{
            display: 'block',
            marginTop: 4,
            fontSize: 11,
            color: allMet ? 'var(--accent-success)' : 'var(--text-tertiary)',
          }}
        >
          {allMet ? t('auth.passwordStrength.allMet') : t('auth.passwordStrength.hint')}
        </Text>
      )}
    </div>
  );
}

export default function RegisterPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const register = useAuthStore((s) => s.register);
  const navigate = useNavigate();
  const { message: msg } = AntdApp.useApp();

  // Task 55: 监听 password 字段值，实时更新 strength bar
  const passwordValue = Form.useWatch('password', form) as string | undefined;

  const onFinish = async (values: { username: string; email: string; password: string; confirm: string }) => {
    if (values.password !== values.confirm) {
      msg.error(t('auth.passwordMismatch'));
      return;
    }
    setLoading(true);
    try {
      await register(values.username, values.email, values.password);
      msg.success(t('auth.registerSuccess'));
      navigate('/');
    } catch (e: unknown) {
      msg.error(getErrorMessage(e) || t('auth.registerFailed'));
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
        background: 'var(--bg-primary)',
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
          background: 'radial-gradient(circle, var(--accent-primary) 0%, transparent 70%)',
          opacity: 0.04,
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
          background: 'radial-gradient(circle, var(--accent-secondary) 0%, transparent 70%)',
          opacity: 0.03,
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
              background: 'linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 20px',
              boxShadow: '0 8px 24px rgba(59,130,246,0.25)',
            }}
          >
            <Sparkles size={28} color="#ffffff" strokeWidth={1.8} />
          </div>
          <Title level={3} style={{ marginBottom: 8, fontWeight: 700, color: 'var(--text-primary)' }}>
            {t('auth.createAccount')}
          </Title>
          <Text style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
            {t('auth.registerSubtitle')}
          </Text>
        </div>

        <div
          style={{
            background: 'var(--bg-secondary)',
            borderRadius: 12,
            padding: 32,
            boxShadow: 'var(--shadow-md)',
            border: '1px solid var(--border-color)',
          }}
        >
          <Form
            name="register"
            form={form}
            onFinish={onFinish}
            autoComplete="off"
            layout="vertical"
          >
            <Form.Item
              name="username"
              label={t('auth.username')}
              validateFirst
              hasFeedback
              rules={[
                { required: true, message: t('auth.usernameRequired') },
                { min: 3, message: t('auth.usernameMinLength') },
              ]}
            >
              <Input placeholder={t('auth.usernamePlaceholder')} size="large" />
            </Form.Item>
            <Form.Item
              name="email"
              label={t('auth.email')}
              validateFirst
              hasFeedback
              rules={[
                { required: true, message: t('auth.emailRequired') },
                { type: 'email', message: t('auth.emailInvalid') },
              ]}
            >
              <Input placeholder={t('auth.emailPlaceholder')} size="large" />
            </Form.Item>
            <Form.Item
              name="password"
              label={t('auth.password')}
              validateFirst
              hasFeedback
              rules={createPasswordRules(t)}
            >
              <Input.Password placeholder={t('auth.passwordPlaceholder')} size="large" />
            </Form.Item>
            {/* Task 55: 密码强度可视化（5 段 strength bar） */}
            <PasswordStrengthBar value={passwordValue || ''} />
            <Form.Item
              name="confirm"
              label={t('auth.confirmPassword')}
              dependencies={['password']}
              validateFirst
              hasFeedback
              // 失焦时实时校验匹配；同时保留 onChange 校验以显示同步反馈
              validateTrigger={['onBlur', 'onChange']}
              rules={[
                { required: true, message: t('auth.confirmPasswordRequired') },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('password') === value) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error(t('auth.passwordMismatch')));
                  },
                }),
              ]}
            >
              <Input.Password placeholder={t('auth.confirmPasswordPlaceholder')} size="large" />
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
                {t('auth.register')}
              </Button>
            </Form.Item>
            <div style={{ textAlign: 'center' }}>
              <Text style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                {t('auth.hasAccount')}{' '}
                <Button
                  type="link"
                  onClick={() => navigate('/login')}
                  style={{
                    color: 'var(--text-primary)',
                    fontWeight: 500,
                    padding: 0,
                    height: 'auto',
                    borderBottom: '1px solid var(--border-color)',
                    borderRadius: 0,
                  }}
                >
                  {t('auth.loginNow')}
                </Button>
              </Text>
            </div>
          </Form>
        </div>

        <div style={{ textAlign: 'center', marginTop: 32 }}>
          <Text style={{ color: 'var(--text-tertiary)', fontSize: 12 }}>
            {t('auth.copyright')}
          </Text>
        </div>
      </div>
    </div>
  );
}

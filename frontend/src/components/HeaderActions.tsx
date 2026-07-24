import { Button, Dropdown, Avatar, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { Sun, Moon, Languages } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { User } from '../types';

const { Text } = Typography;

interface Props {
  user: User | null;
  themeMode: 'light' | 'dark';
  currentLang: string;
  userMenuItems: MenuProps['items'];
  onToggleLanguage: () => void;
  onToggleTheme: () => void;
}

/**
 * Header 右侧操作区: 语言切换 / 主题切换 / 用户菜单. 从 Layout 拆出 (Task 27.2)
 * 不包含通知 Popover (由 NotificationPopover 独立组件处理).
 */
export default function HeaderActions({
  user,
  themeMode,
  currentLang,
  userMenuItems,
  onToggleLanguage,
  onToggleTheme,
}: Props) {
  const { t } = useTranslation();

  return (
    <>
      <Button
        type="text"
        icon={<Languages size={18} strokeWidth={1.8} />}
        onClick={onToggleLanguage}
        aria-label={t('nav.toggleLanguage')}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, fontSize: 12 }}
      >
        {currentLang === 'zh-CN' ? 'EN' : '中'}
      </Button>
      <Button
        type="text"
        icon={themeMode === 'dark' ? <Sun size={18} strokeWidth={1.8} /> : <Moon size={18} strokeWidth={1.8} />}
        aria-label={t('nav.toggleTheme')}
        onClick={onToggleTheme}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      />
      <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={['click', 'hover']}>
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
    </>
  );
}

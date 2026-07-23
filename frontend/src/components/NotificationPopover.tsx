import { Popover, Badge, Button, List, Typography } from 'antd';
import { Bell } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { WSNotification } from '../hooks/useWebSocket';

/** WSNotification 本地持久化时附加客户端时间戳, 用于未读数过滤 */
export interface NotifItem extends WSNotification {
  timestamp: number;
}

interface Props {
  open: boolean;
  notifications: NotifItem[];
  readAt: number;
  onOpenChange: (open: boolean) => void;
  onClear: () => void;
}

/**
 * 通知 Popover: 从 Layout 拆出 (Task 27.2)
 * 内部不持有状态, 由父组件 Layout 管理 notifications/readAt 并传入.
 */
export default function NotificationPopover({
  open,
  notifications,
  readAt,
  onOpenChange,
  onClear,
}: Props) {
  const { t } = useTranslation();
  const unreadCount = notifications.filter((n) => n.timestamp > readAt).length;
  const { Text } = Typography;

  return (
    <Popover
      open={open}
      onOpenChange={onOpenChange}
      trigger="click"
      placement="bottomRight"
      title={t('notification.title')}
      content={
        <div style={{ width: 320, maxHeight: 360, overflow: 'auto' }}>
          {notifications.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-secondary)' }}>
              {t('notification.empty')}
            </div>
          ) : (
            <List
              dataSource={notifications}
              renderItem={(item, index) => (
                <List.Item
                  key={`${item.type}-${item.timestamp}-${index}`}
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
              <Button type="link" size="small" onClick={onClear}>
                {t('notification.clear')}
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
          aria-label={t('notification.title')}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        />
      </Badge>
    </Popover>
  );
}

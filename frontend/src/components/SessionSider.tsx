import { Layout, Button } from 'antd';
import { Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatSession } from '../types';

const { Sider } = Layout;

interface Props {
  siderVisible: boolean;
  sessions: ChatSession[];
  sessionIdNum: number;
  onNavigate: (id: number) => void;
  onDeleteSession: (id: number) => void;
  onNewSessionClick: () => void;
  getKBName: (kbId: number | null) => string;
}

/**
 * 左侧会话列表 Sider: 从 ChatPage 拆出 (Task 27.4)
 * 不持有状态, sessions/currentSessionId 由父组件传入.
 */
export default function SessionSider({
  siderVisible,
  sessions,
  sessionIdNum,
  onNavigate,
  onDeleteSession,
  onNewSessionClick,
  getKBName,
}: Props) {
  const { t } = useTranslation();

  return (
    <Sider
      width={280}
      style={{ background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)' }}
      trigger={null}
      collapsible
      collapsed={!siderVisible}
      collapsedWidth={0}
    >
      <div style={{ padding: 16, borderBottom: '1px solid var(--border-color-light)' }}>
        <Button
          type="primary"
          icon={<Plus size={16} />}
          block
          onClick={onNewSessionClick}
        >
          {t('chat.newChat')}
        </Button>
      </div>
      <div style={{ overflow: 'auto', height: 'calc(100% - 60px)' }}>
        {sessions.map((s) => (
          <div
            key={s.id}
            role="button"
            tabIndex={0}
            onClick={() => onNavigate(s.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onNavigate(s.id);
              }
            }}
            className={`chat-session-item${s.id === sessionIdNum ? ' is-active' : ''}`}
            style={{
              padding: '10px 16px',
              cursor: 'pointer',
              borderLeft: s.id === sessionIdNum ? '3px solid var(--accent-primary)' : '3px solid transparent',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <div
                  style={{
                    fontWeight: s.id === sessionIdNum ? 600 : 400,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    fontSize: 14,
                  }}
                >
                  {s.title || t('chat.newSession')}
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {getKBName(s.kb_id)}
                </div>
              </div>
              <Button
                type="text"
                danger
                size="small"
                icon={<Trash2 size={14} />}
                aria-label={t('chat.deleteSession')}
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(s.id);
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </Sider>
  );
}

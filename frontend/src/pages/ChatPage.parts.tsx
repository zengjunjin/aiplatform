import type { RefObject } from 'react';
import { Layout, Button, Tag, Breadcrumb, Select, Tooltip } from 'antd';
import { BookOpen, Menu, Sparkles, Coins } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MessageBubble } from '../components/MessageBubble';
import type { ChatSession, MessageWithRefs, Reference } from '../types';

const { Content } = Layout;

interface TokenSummary {
  input: number;
  output: number;
  total: number;
}

// ===== ChatHeader: 顶部栏 (侧边栏切换 / 面包屑 / KB 标签 / token 徽章) =====
export interface ChatHeaderProps {
  onToggleSider: () => void;
  currentSession: ChatSession | undefined;
  getKBName: (kbId: number | null) => string;
  totalTokens: TokenSummary | null;
}

export function ChatHeader({
  onToggleSider,
  currentSession,
  getKBName,
  totalTokens,
}: ChatHeaderProps) {
  const { t } = useTranslation();
  return (
    <div
      style={{
        padding: '0 16px',
        height: 52,
        display: 'flex',
        alignItems: 'center',
        borderBottom: '1px solid var(--border-color-light)',
        background: 'var(--bg-secondary)',
      }}
    >
      <Button
        type="text"
        icon={<Menu size={18} />}
        aria-label={t('chat.toggleSidebar')}
        onClick={onToggleSider}
      />
      <Breadcrumb style={{ marginLeft: 12 }}>
        <Breadcrumb.Item>
          <Link to="/chat">{t('chat.chat')}</Link>
        </Breadcrumb.Item>
        <Breadcrumb.Item>
          {currentSession?.title || t('chat.loading')}
        </Breadcrumb.Item>
      </Breadcrumb>
      {currentSession?.kb_id && (
        <Tag color="blue" style={{ marginLeft: 'auto' }}>
          <BookOpen size={12} style={{ marginRight: 4 }} />
          {getKBName(currentSession.kb_id)}
        </Tag>
      )}
      {/* Task 39: 会话累计 token 徽章 (KB Tag 右侧; 数据不可用时不显示) */}
      {totalTokens && (
        <Tooltip
          title={t('chat.totalTokensTooltip', {
            input: totalTokens.input,
            output: totalTokens.output,
          })}
          placement="bottom"
        >
          <Tag
            style={{
              marginLeft: currentSession?.kb_id ? 8 : 'auto',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <Coins size={12} />
            {t('chat.totalTokens', { count: totalTokens.total })}
          </Tag>
        </Tooltip>
      )}
    </div>
  );
}

// ===== ChatMessagesArea: 消息列表 (含空状态引导) =====
export interface ChatMessagesAreaProps {
  sessionMsgs: MessageWithRefs[];
  streaming: boolean;
  scrollContainerRef: RefObject<HTMLDivElement>;
  messagesEndRef: RefObject<HTMLDivElement>;
  onRegenerate: () => void;
  onShowReferences: (refs: Reference[]) => void;
}

export function ChatMessagesArea({
  sessionMsgs,
  streaming,
  scrollContainerRef,
  messagesEndRef,
  onRegenerate,
  onShowReferences,
}: ChatMessagesAreaProps) {
  const { t } = useTranslation();
  return (
    <Content
      ref={scrollContainerRef}
      aria-live="polite"
      aria-atomic="true"
      style={{
        padding: '16px 24px',
        overflow: 'auto',
        background: 'var(--bg-tertiary)',
      }}
    >
      {sessionMsgs.length === 0 ? (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          minHeight: 400,
          padding: '40px 0',
        }}>
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: 20,
              background: 'linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 50%, var(--accent-primary-light) 100%)',
              backgroundSize: '200% 200%',
              animation: 'logoGradient 4s ease infinite',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: 24,
              boxShadow: '0 8px 32px rgba(59, 130, 246, 0.25)',
            }}
          >
            <Sparkles size={36} color="#ffffff" strokeWidth={1.5} />
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 8px 0' }}>
            {t('chat.startFirstChat')}
          </h2>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', margin: '0 0 32px 0' }}>
            {t('chat.selectKBAndAsk')}
          </p>
          <div style={{
            width: '100%',
            maxWidth: 600,
            padding: '24px',
            background: 'var(--bg-secondary)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-md)',
            border: '1px solid var(--border-color)',
          }}>
            <p style={{ fontSize: 13, color: 'var(--text-tertiary)', textAlign: 'center', margin: 0 }}>
              {t('chat.askAnything')}
            </p>
          </div>
        </div>
      ) : (
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          {sessionMsgs.map((msg, idx) => {
            // Task 40: 消息数 > 100 时启用 content-visibility 软窗口化
            // 浏览器自动跳过不可见消息的渲染, 保持滚动行为不变
            const isLast = idx === sessionMsgs.length - 1;
            const enableVirtualization = sessionMsgs.length > 100;
            // 最近 5 条消息不启用 content-visibility, 确保流式更新和滚动到底部行为正常
            const shouldVirtualize = enableVirtualization && idx < sessionMsgs.length - 5;
            return (
            <div
              key={msg.id || `msg-${idx}`}
              className="message-bubble-enter"
              style={shouldVirtualize ? {
                contentVisibility: 'auto',
                containIntrinsicSize: 'auto 120px',
              } : undefined}
            >
              <MessageBubble
                role={msg.role}
                content={msg.content}
                messageId={msg.id}
                isStreaming={msg.isStreaming}
                references={msg.references}
                createdAt={msg.created_at}
                onRegenerate={
                  msg.role === 'assistant' && !msg.isStreaming && !streaming && isLast
                    ? onRegenerate
                    : undefined
                }
                tokenInput={msg.token_input}
                tokenOutput={msg.token_output}
                latencyMs={msg.latency_ms}
              />
              {msg.references && msg.references.length > 0 && !msg.isStreaming && (
                <div style={{ marginLeft: 48, marginBottom: 16 }}>
                  <Tag
                    color="blue"
                    style={{ cursor: 'pointer' }}
                    onClick={() => { if (msg.references) onShowReferences(msg.references); }}
                    aria-label={t('chat.reference')}
                    role="listitem"
                  >
                    {t('chat.viewReferencesCount', { count: msg.references.length })}
                  </Tag>
                </div>
              )}
            </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>
      )}
    </Content>
  );
}

// ===== ChatModelSelector: 模型选择下拉框 =====
export interface ChatModelSelectorProps {
  selectedModel: string;
  onChange: (model: string) => void;
  modelOptions: { label: string; value: string; disabled: boolean }[];
}

export function ChatModelSelector({
  selectedModel,
  onChange,
  modelOptions,
}: ChatModelSelectorProps) {
  const { t } = useTranslation();
  return (
    <div style={{ padding: '8px 24px 0', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border-color)' }}>
      <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{t('chat.model')}</span>
        <Select
          value={selectedModel || undefined}
          onChange={onChange}
          placeholder={t('chat.modelAuto')}
          style={{ minWidth: 200 }}
          size="small"
          allowClear
          options={modelOptions}
        />
      </div>
    </div>
  );
}

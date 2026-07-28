import { memo, useState, useEffect, useCallback } from 'react';
import { Avatar, Card, Tooltip, Button, Tag, App as AntdApp } from 'antd';
import { User, Bot, Copy, RefreshCw, ThumbsUp, ThumbsDown, Timer, Coins } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { MarkdownRenderer } from './MarkdownRenderer';
import FeedbackModal from './FeedbackModal';
import { copyToClipboard, formatTime } from '../utils/format';
import { useChatStore } from '../store/chat';
import { feedbackApi } from '../api/chat';
import type { Reference } from '../types';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  messageId?: number;
  isStreaming?: boolean;
  references?: Reference[];
  createdAt?: string;
  onRegenerate?: () => void;
  /** Task 39: token 消耗与响应时长, 仅 assistant 消息有效; 后端历史消息返回, 流式消息在 done 事件后下次 fetchMessages 填充 */
  tokenInput?: number | null;
  tokenOutput?: number | null;
  latencyMs?: number | null;
}

function MessageBubbleBase({
  role,
  content,
  messageId,
  isStreaming,
  references,
  createdAt,
  onRegenerate,
  tokenInput,
  tokenOutput,
  latencyMs,
}: Props) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();

  // 反馈状态: 从 store 缓存读取, 命中缓存不会重复拉取
  const feedback = useChatStore(
    (s) => (messageId != null ? s.feedbackByMessageId[messageId] : undefined)
  );
  const getFeedbackAction = useChatStore((s) => s.getFeedback);
  const setFeedbackStore = useChatStore((s) => s.setFeedback);
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [likeSubmitting, setLikeSubmitting] = useState(false);

  // 触发拉取 feedback (仅在缓存未命中时由 store 内部发起请求)
  // Task 23 (P1-FE-09): AbortController 防止组件卸载后 store 仍发起请求
  useEffect(() => {
    if (role !== 'assistant' || !messageId || isStreaming) {
      return;
    }
    const abortController = new AbortController();
    getFeedbackAction(messageId, abortController.signal);
    return () => { abortController.abort(); };
  }, [role, messageId, isStreaming, getFeedbackAction]);

  const handleCopy = useCallback(async () => {
    const ok = await copyToClipboard(content).catch(() => false);
    if (ok) {
      message.success(t('chat.copied'));
    } else {
      message.error(t('chat.copyFailed'));
    }
  }, [content, t, message]);

  const handleLike = useCallback(async () => {
    if (!messageId) return;
    setLikeSubmitting(true);
    try {
      const res = await feedbackApi.submitFeedback(messageId, {
        rating: 1,
      });
      setFeedbackStore(messageId, res);
      message.success(t('chat.feedbackThanks'));
    } catch {
      message.error(t('chat.feedbackFailed'));
    } finally {
      setLikeSubmitting(false);
    }
  }, [messageId, t, message, setFeedbackStore]);

  const handleDislike = useCallback(() => {
    if (!messageId) return;
    setFeedbackModalOpen(true);
  }, [messageId]);

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        marginBottom: 24,
        flexDirection: role === 'user' ? 'row-reverse' : 'row',
      }}
    >
      <Avatar
        style={{
          backgroundColor: role === 'user' ? 'var(--accent-primary-light)' : 'var(--accent-success-light)',
          flexShrink: 0,
        }}
        icon={role === 'user' ? <User size={18} /> : <Bot size={18} />}
      />
      <div style={{ maxWidth: '70%' }}>
        <Card
          size="small"
          {...(isStreaming ? { 'aria-live': 'polite' as const } : {})}
          {...(content.includes('❌') || content.includes('**' + t('chat.errorLabel') + '**') ? { role: 'alert', 'aria-live': 'assertive' as const } : {})}
          style={{
            background: role === 'user' ? 'var(--accent-info-bg)' : 'var(--bg-secondary)',
            border: 'none',
            borderRadius: 'var(--radius-md)',
            boxShadow: role === 'assistant' ? 'var(--shadow-sm)' : 'none',
          }}
        >
          {content ? (
            <>
              <MarkdownRenderer content={content} />
              {isStreaming && (
                <span className="streaming-cursor" style={{
                  display: 'inline-block',
                  width: 2,
                  height: 16,
                  backgroundColor: 'var(--text-primary)',
                  marginLeft: 2,
                  animation: 'blink 1s step-end infinite',
                  verticalAlign: 'text-bottom',
                }} />
              )}
            </>
          ) : (
            isStreaming && (
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <span className="thinking-dots">
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
                <span style={{ color: 'var(--text-tertiary)', fontSize: 13, marginLeft: 4 }}>
                  {t('chat.thinking')}
                </span>
              </div>
            )
          )}

          {role === 'assistant' && !isStreaming && content && (
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: '1px solid var(--border-color-light)',
                display: 'flex',
                gap: 8,
                fontSize: 12,
                color: 'var(--text-tertiary)',
                alignItems: 'center',
              }}
            >
              <Tooltip title={t('chat.copy')}>
                <Button
                  type="text"
                  size="small"
                  icon={<Copy size={14} />}
                  aria-label={t('chat.copy')}
                  onClick={handleCopy}
                />
              </Tooltip>
              {onRegenerate && (
                <Tooltip title={t('chat.regenerate')}>
                  <Button
                    type="text"
                    size="small"
                    icon={<RefreshCw size={14} />}
                    aria-label={t('chat.regenerate')}
                    onClick={onRegenerate}
                  />
                </Tooltip>
              )}

              {/* 反馈按钮 */}
              <Tooltip title={t('chat.like')}>
                <Button
                  type="text"
                  size="small"
                  icon={<ThumbsUp size={14} />}
                  aria-label={t('chat.like')}
                  onClick={handleLike}
                  loading={likeSubmitting && feedback?.rating !== 1}
                  style={{
                    color: feedback?.rating === 1 ? 'var(--accent-primary-light)' : undefined,
                  }}
                />
              </Tooltip>
              <Tooltip title={t('chat.dislike')}>
                <Button
                  type="text"
                  size="small"
                  icon={<ThumbsDown size={14} />}
                  aria-label={t('chat.dislike')}
                  onClick={handleDislike}
                  style={{
                    color: feedback?.rating === -1 ? 'var(--accent-danger-light)' : undefined,
                  }}
                />
              </Tooltip>

              {references && references.length > 0 && (
                <Tag color="blue" style={{ marginLeft: 'auto' }}>
                  📚 {t('chat.referencesCount', { count: references.length })}
                </Tag>
              )}

              {/* Task 39: token chip + 响应时长 chip (数据不可用时显示 "-") */}
              {(tokenInput != null || tokenOutput != null) && (
                <Tooltip title={t('chat.tokensTooltip')}>
                  <Tag style={{ marginInlineEnd: 0, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                    <Coins size={12} />
                    {t('chat.tokens', {
                      input: tokenInput ?? '-',
                      output: tokenOutput ?? '-',
                    })}
                  </Tag>
                </Tooltip>
              )}
              {latencyMs != null && latencyMs > 0 && (
                <Tooltip title={t('chat.latencyTooltip')}>
                  <Tag style={{ marginInlineEnd: 0, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                    <Timer size={12} />
                    {latencyMs >= 1000
                      ? t('chat.latencySeconds', { s: (latencyMs / 1000).toFixed(1) })
                      : t('chat.latencyMillis', { ms: latencyMs })}
                  </Tag>
                </Tooltip>
              )}
            </div>
          )}
        </Card>
        <div
          style={{
            fontSize: 11,
            color: 'var(--text-tertiary)',
            marginTop: 4,
            textAlign: role === 'user' ? 'right' : 'left',
          }}
        >
          {createdAt ? formatTime(createdAt) : ''}
        </div>
      </div>

      <FeedbackModal
        open={feedbackModalOpen}
        messageId={messageId}
        onClose={() => setFeedbackModalOpen(false)}
        onSubmitted={(fb) => {
          if (messageId) setFeedbackStore(messageId, fb);
        }}
      />
    </div>
  );
}

// Task 71: 改用 React.memo 默认浅比较, 移除自定义 areEqual
// references 引用稳定性由 chat store 的 updateAssistant 保证 (仅在 finalRefs 非空时赋值, 否则 spread 继承)
// onRegenerate 仅在非 streaming 的最后一条 assistant 消息上传入; streaming 期间所有消息该 prop 为 undefined,
// 故 handleRegenerate 引用变化不会导致 streaming 期间的额外重渲染
export const MessageBubble = memo(MessageBubbleBase);

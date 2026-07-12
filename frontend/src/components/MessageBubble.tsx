import { memo, useState, useEffect, useCallback } from 'react';
import { Avatar, Card, Tooltip, Button, Tag, Modal, Radio, Input, Space } from 'antd';
import { App as AntdApp } from 'antd';
import { User, Bot, Copy, RefreshCw, ThumbsUp, ThumbsDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { MarkdownRenderer } from './MarkdownRenderer';
import { copyToClipboard, formatTime } from '../utils/format';
import { feedbackApi } from '../api/chat';
import type { Reference } from '../types';
import type { FeedbackOut } from '../api/chat';

const FEEDBACK_TYPE_OPTIONS = [
  { value: 'not_accurate', label: 'chat.feedbackType.notAccurate' },
  { value: 'incomplete', label: 'chat.feedbackType.incomplete' },
  { value: 'hallucination', label: 'chat.feedbackType.hallucination' },
  { value: 'irrelevant', label: 'chat.feedbackType.irrelevant' },
  { value: 'too_verbose', label: 'chat.feedbackType.tooVerbose' },
  { value: 'too_brief', label: 'chat.feedbackType.tooBrief' },
  { value: 'other', label: 'chat.feedbackType.other' },
];

interface Props {
  role: 'user' | 'assistant';
  content: string;
  messageId?: number;
  isStreaming?: boolean;
  references?: Reference[];
  createdAt?: string;
  onCopy?: () => void;
  onRegenerate?: () => void;
}

function MessageBubbleBase({
  role,
  content,
  messageId,
  isStreaming,
  references,
  createdAt,
  onRegenerate,
}: Props) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();

  // 反馈状态
  const [feedback, setFeedback] = useState<FeedbackOut | null>(null);
  const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
  const [feedbackType, setFeedbackType] = useState<string>('');
  const [feedbackComment, setFeedbackComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // 加载已有反馈
  useEffect(() => {
    if (role === 'assistant' && messageId && !isStreaming) {
      let cancelled = false;
      feedbackApi.getFeedback(messageId).then((fb) => {
        if (!cancelled && fb) setFeedback(fb);
      }).catch(() => {});
      return () => {
        cancelled = true;
      };
    }
  }, [role, messageId, isStreaming]);

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
    setSubmitting(true);
    try {
      const fb = await feedbackApi.submitFeedback(messageId, {
        rating: 1,
      });
      setFeedback(fb);
      message.success(t('chat.feedbackThanks'));
    } catch {
      message.error(t('chat.feedbackFailed'));
    } finally {
      setSubmitting(false);
    }
  }, [messageId, t, message]);

  const handleDislike = useCallback(() => {
    if (!messageId) return;
    setFeedbackType('');
    setFeedbackComment('');
    setFeedbackModalOpen(true);
  }, [messageId]);

  const handleDislikeSubmit = useCallback(async () => {
    if (!messageId) return;
    setSubmitting(true);
    try {
      const fb = await feedbackApi.submitFeedback(messageId, {
        rating: -1,
        comment: feedbackComment || undefined,
        feedback_type: feedbackType || undefined,
      });
      setFeedback(fb);
      setFeedbackModalOpen(false);
      message.success(t('chat.feedbackThanks'));
    } catch {
      message.error(t('chat.feedbackFailed'));
    } finally {
      setSubmitting(false);
    }
  }, [messageId, feedbackComment, feedbackType, t, message]);

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
          backgroundColor: role === 'user' ? '#1677ff' : '#52c41a',
          flexShrink: 0,
        }}
        icon={role === 'user' ? <User size={18} /> : <Bot size={18} />}
      />
      <div style={{ maxWidth: '70%' }}>
        <Card
          size="small"
          style={{
            background: role === 'user' ? '#e6f4ff' : 'var(--bg-secondary)',
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
                <span style={{ color: '#999', fontSize: 13, marginLeft: 4 }}>
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
                borderTop: '1px solid #f0f0f0',
                display: 'flex',
                gap: 8,
                fontSize: 12,
                color: '#999',
                alignItems: 'center',
              }}
            >
              <Tooltip title={t('chat.copy')}>
                <Button
                  type="text"
                  size="small"
                  icon={<Copy size={14} />}
                  onClick={handleCopy}
                />
              </Tooltip>
              {onRegenerate && (
                <Tooltip title={t('chat.regenerate')}>
                  <Button
                    type="text"
                    size="small"
                    icon={<RefreshCw size={14} />}
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
                  onClick={handleLike}
                  loading={submitting && feedback?.rating !== 1}
                  style={{
                    color: feedback?.rating === 1 ? '#1677ff' : undefined,
                  }}
                />
              </Tooltip>
              <Tooltip title={t('chat.dislike')}>
                <Button
                  type="text"
                  size="small"
                  icon={<ThumbsDown size={14} />}
                  onClick={handleDislike}
                  loading={submitting && feedback?.rating !== -1}
                  style={{
                    color: feedback?.rating === -1 ? '#ff4d4f' : undefined,
                  }}
                />
              </Tooltip>

              {references && references.length > 0 && (
                <Tag color="blue" style={{ marginLeft: 'auto' }}>
                  📚 {t('chat.referencesCount', { count: references.length })}
                </Tag>
              )}
            </div>
          )}
        </Card>
        <div
          style={{
            fontSize: 11,
            color: '#bbb',
            marginTop: 4,
            textAlign: role === 'user' ? 'right' : 'left',
          }}
        >
          {createdAt ? formatTime(createdAt) : ''}
        </div>
      </div>

      {/* 点踩反馈弹窗 */}
      <Modal
        title={t('chat.feedbackTitle')}
        open={feedbackModalOpen}
        onOk={handleDislikeSubmit}
        onCancel={() => setFeedbackModalOpen(false)}
        confirmLoading={submitting}
        okText={t('common.confirm')}
        cancelText={t('common.cancel')}
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>
            {t('chat.feedbackTypeLabel')}
          </div>
          <Radio.Group
            value={feedbackType}
            onChange={(e) => setFeedbackType(e.target.value)}
          >
            <Space direction="vertical">
              {FEEDBACK_TYPE_OPTIONS.map((opt) => (
                <Radio key={opt.value} value={opt.value}>
                  {t(opt.label)}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </div>
        <div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>
            {t('chat.feedbackCommentLabel')}
          </div>
          <Input.TextArea
            value={feedbackComment}
            onChange={(e) => setFeedbackComment(e.target.value)}
            placeholder={t('chat.feedbackCommentPlaceholder')}
            rows={3}
            maxLength={500}
          />
        </div>
      </Modal>
    </div>
  );
}

export const MessageBubble = memo(MessageBubbleBase);
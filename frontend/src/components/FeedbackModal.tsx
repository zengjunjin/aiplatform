import { useState, useCallback } from 'react';
import { Modal, Radio, Input, Space, App as AntdApp } from 'antd';
import { useTranslation } from 'react-i18next';
import { feedbackApi } from '../api/chat';
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
  open: boolean;
  messageId?: number;
  onClose: () => void;
  /** 提交成功后回调, 由父组件写入 store 缓存 */
  onSubmitted: (feedback: FeedbackOut) => void;
}

/**
 * 点踩反馈弹窗: 从 MessageBubble 拆出 (Task 27.3)
 * 内部维护 feedbackType/feedbackComment/submitting 状态, 提交成功后通知父组件.
 */
export default function FeedbackModal({ open, messageId, onClose, onSubmitted }: Props) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const [feedbackType, setFeedbackType] = useState<string>('');
  const [feedbackComment, setFeedbackComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!messageId) return;
    setSubmitting(true);
    try {
      const res = await feedbackApi.submitFeedback(messageId, {
        rating: -1,
        comment: feedbackComment || undefined,
        feedback_type: feedbackType || undefined,
      });
      onSubmitted(res);
      onClose();
      message.success(t('chat.feedbackThanks'));
    } catch {
      message.error(t('chat.feedbackFailed'));
    } finally {
      setSubmitting(false);
    }
  }, [messageId, feedbackComment, feedbackType, onSubmitted, onClose, message, t]);

  return (
    <Modal
      title={t('chat.feedbackTitle')}
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      confirmLoading={submitting}
      okText={t('common.confirm')}
      transitionName=""
      maskTransitionName=""
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
  );
}

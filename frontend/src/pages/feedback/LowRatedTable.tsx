import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, Table, Tag, Empty, Typography, App as AntdApp } from 'antd';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import { feedbackApi } from '../../api/chat';
import type { FeedbackDetail } from '../../api/chat';
import { getErrorMessage } from '../../utils/errorReporter';
import { FEEDBACK_TYPE_LABELS } from '../../constants/feedback';

const { Paragraph } = Typography;

const FEEDBACK_TYPE_COLORS: Record<string, string> = {
  not_accurate: 'orange',
  incomplete: 'blue',
  hallucination: 'red',
  irrelevant: 'purple',
  too_verbose: 'cyan',
  too_brief: 'geekblue',
  other: 'default',
};

interface LowRatedTableProps {
  selectedKbId: number | undefined;
  dateRange: [dayjs.Dayjs, dayjs.Dayjs] | null;
  selectedType: string | undefined;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  /** feedbacks 变化时通知容器（用于 FeedbackTypeChart 的 dailyStackedOption） */
  onFeedbacksChange: (feedbacks: FeedbackDetail[]) => void;
}

/**
 * Task 4.2: 从 FeedbackPage 抽出的低分回答列表。
 * 内部维护 feedbacks + fetchFeedbacks useEffect（按筛选条件 + 分页变化重新拉取）。
 * Task 5.4: columns 用 useMemo 缓存（原代码是普通数组，每次渲染新建）。
 */
export default function LowRatedTable({
  selectedKbId,
  dateRange,
  selectedType,
  page,
  pageSize,
  onPageChange,
  onFeedbacksChange,
}: LowRatedTableProps) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const [feedbacks, setFeedbacks] = useState<FeedbackDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);

  const fetchFeedbacks = useCallback(async () => {
    setLoading(true);
    try {
      const result = await feedbackApi.getLowRated({
        kb_id: selectedKbId,
        start_date: dateRange?.[0]?.toISOString(),
        end_date: dateRange?.[1]?.toISOString(),
        feedback_type: selectedType,
        page,
        page_size: pageSize,
      });
      setFeedbacks(result.items);
      setTotal(result.total);
      onFeedbacksChange(result.items);
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('feedback.loadFeedbacksFailed'));
    } finally {
      setLoading(false);
    }
  }, [selectedKbId, dateRange, selectedType, page, pageSize, message, t, onFeedbacksChange]);

  useEffect(() => {
    fetchFeedbacks();
  }, [fetchFeedbacks]);

  // Task 5.4: columns 用 useMemo 缓存
  const columns = useMemo(() => [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
    },
    {
      title: t('chat.feedbackTypeLabel'),
      dataIndex: 'feedback_type',
      width: 130,
      render: (type: string | null) => {
        if (!type) return <Tag>{t('feedback.na')}</Tag>;
        const label = FEEDBACK_TYPE_LABELS[type];
        const color = FEEDBACK_TYPE_COLORS[type] || 'default';
        return <Tag color={color}>{label ? t(label) : type}</Tag>;
      },
    },
    {
      title: t('chat.feedbackCommentLabel'),
      dataIndex: 'comment',
      width: 200,
      ellipsis: true,
      render: (comment: string | null) => comment || '-',
    },
    {
      title: t('feedback.question'),
      dataIndex: 'question',
      width: 250,
      ellipsis: true,
    },
    {
      title: t('feedback.answer'),
      dataIndex: 'answer',
      width: 250,
      ellipsis: true,
    },
    {
      title: t('feedback.kbId'),
      dataIndex: 'kb_id',
      width: 80,
      render: (kbId: number | null) => kbId ? `#${kbId}` : '-',
    },
    {
      title: t('feedback.time'),
      dataIndex: 'created_at',
      width: 170,
      render: (time: string) => dayjs(time).format('YYYY-MM-DD HH:mm'),
    },
  ], [t]);

  return (
    <Card title={t('feedback.lowRatedAnswers')}>
      <Table
        dataSource={feedbacks}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: (p) => onPageChange(p),
          showSizeChanger: false,
          showTotal: (total) => t('feedback.totalItems', { count: total }),
        }}
        expandable={{
          expandedRowRender: (record) => (
            <div style={{ padding: 16 }}>
              <Card
                title={t('feedback.question')}
                size="small"
                style={{ marginBottom: 12, background: '#f6ffed' }}
              >
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {record.question || t('feedback.noQuestion')}
                </Paragraph>
              </Card>
              <Card
                title={t('feedback.systemAnswer')}
                size="small"
                style={{ marginBottom: 12, background: '#fff7e6' }}
              >
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {record.answer}
                </Paragraph>
              </Card>
              {record.comment && (
                <Card
                  title={t('feedback.userFeedback')}
                  size="small"
                  style={{ background: 'var(--bg-tertiary)' }}
                >
                  <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                    {record.comment}
                  </Paragraph>
                </Card>
              )}
            </div>
          ),
        }}
        locale={{ emptyText: <Empty description={t('feedback.noFeedbackData')} /> }}
      />
    </Card>
  );
}

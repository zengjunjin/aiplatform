import { useState, useEffect, useCallback } from 'react';
import { Card, Statistic, Row, Col, Spin, App as AntdApp } from 'antd';
import { ThumbsUp, ThumbsDown, MessageSquare } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { feedbackApi } from '../../api/chat';
import type { FeedbackStats } from '../../api/chat';
import { getErrorMessage } from '../../utils/errorReporter';

interface FeedbackStatsOverviewProps {
  selectedKbId: number | undefined;
  /** stats 变化时通知容器（用于 FeedbackTypeChart 的 typeBarOption） */
  onStatsChange: (stats: FeedbackStats | null) => void;
}

/**
 * Task 4.2: 从 FeedbackPage 抽出的统计概览卡片。
 * 内部维护 stats 数据 + fetchStats useEffect（按 selectedKbId 变化重新拉取）。
 * 通过 onStatsChange 回调把 stats 传给容器（用于 FeedbackTypeChart）。
 */
export default function FeedbackStatsOverview({ selectedKbId, onStatsChange }: FeedbackStatsOverviewProps) {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  const fetchStats = useCallback(async (signal?: AbortSignal) => {
    setStatsLoading(true);
    try {
      const s = await feedbackApi.getStats(selectedKbId, signal);
      if (signal?.aborted) return;
      setStats(s);
      onStatsChange(s);
    } catch (e: unknown) {
      if (signal?.aborted) return;
      message.error(getErrorMessage(e) || t('feedback.loadStatsFailed'));
    } finally {
      if (!signal?.aborted) setStatsLoading(false);
    }
  }, [selectedKbId, message, t, onStatsChange]);

  // Task 23 (P1-FE-09): AbortController 防止组件卸载后 setState
  useEffect(() => {
    const abortController = new AbortController();
    fetchStats(abortController.signal);
    return () => { abortController.abort(); };
  }, [fetchStats]);

  return (
    <Spin spinning={statsLoading}>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('feedback.totalFeedback')}
              value={stats?.total_feedback || 0}
              prefix={<MessageSquare size={16} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('feedback.positiveRate')}
              value={stats ? (stats.positive_rate * 100).toFixed(1) : 0}
              suffix="%"
              prefix={<ThumbsUp size={16} />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('feedback.negativeRate')}
              value={stats ? (stats.negative_rate * 100).toFixed(1) : 0}
              suffix="%"
              prefix={<ThumbsDown size={16} />}
              valueStyle={{ color: '#cf1322' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title={t('feedback.byType')}
              value={stats ? Object.keys(stats.by_type).length : 0}
              suffix={t('feedback.typesSuffix')}
            />
          </Card>
        </Col>
      </Row>
    </Spin>
  );
}

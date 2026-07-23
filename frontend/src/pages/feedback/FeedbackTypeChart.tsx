import { useMemo } from 'react';
import { Row, Col, Card, Empty } from 'antd';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import dayjs from 'dayjs';
import type { FeedbackStats, FeedbackDetail } from '../../api/chat';
import { FEEDBACK_TYPE_LABELS } from '../../constants/feedback';

interface FeedbackTypeChartProps {
  stats: FeedbackStats | null;
  feedbacks: FeedbackDetail[];
}

/**
 * Task 4.2: 从 FeedbackPage 抽出的类型分布图卡片。
 * 左：类型分布横向条形图（按 count 降序）；右：每日反馈堆叠柱状图。
 * 数据由容器组件传入（stats 来自 FeedbackStatsOverview，feedbacks 来自 LowRatedTable）。
 */
export default function FeedbackTypeChart({ stats, feedbacks }: FeedbackTypeChartProps) {
  const { t } = useTranslation();

  // Task 36: 类型分布横向条形图 (按 count 降序)
  const typeBarOption = useMemo(() => {
    if (!stats || !stats.by_type) return {};
    const entries = Object.entries(stats.by_type)
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => ({
        name: t(FEEDBACK_TYPE_LABELS[type] || type),
        value: count as number,
      }));
    return {
      tooltip: { trigger: 'axis' as const, axisPointer: { type: 'shadow' as const } },
      grid: { left: '3%', right: '8%', bottom: '3%', top: 10, containLabel: true },
      xAxis: { type: 'value' as const, minInterval: 1 },
      yAxis: {
        type: 'category' as const,
        data: entries.map((e) => e.name),
        inverse: false,
      },
      series: [
        {
          name: t('feedback.byType'),
          type: 'bar',
          data: entries.map((e) => e.value),
          itemStyle: { color: '#3b82f6', borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: 'right' as const },
        },
      ],
    };
  }, [stats, t]);

  // Task 36: 每日反馈堆叠柱状图 (按 feedback_type 堆叠)
  // 数据源: 当前 feedbacks 列表 (低分反馈). 正反馈数据后端未提供逐日明细, 此处用低分反馈类型堆叠近似展示.
  // 技术债务: 后续可由后端新增 GET /chat/feedback/daily-stats 端点返回正/负逐日统计.
  const dailyStackedOption = useMemo(() => {
    if (!feedbacks || feedbacks.length === 0) return null;
    // 按日期分组, 每个日期再按 feedback_type 统计
    const dayMap = new Map<string, Record<string, number>>();
    const typeSet = new Set<string>();
    for (const fb of feedbacks) {
      const day = dayjs(fb.created_at).format('MM-DD');
      let bucket = dayMap.get(day);
      if (!bucket) {
        bucket = {};
        dayMap.set(day, bucket);
      }
      const tp = fb.feedback_type || 'other';
      typeSet.add(tp);
      bucket[tp] = (bucket[tp] || 0) + 1;
    }
    const days = Array.from(dayMap.keys()).sort();
    const types = Array.from(typeSet);
    const series = types.map((tp) => ({
      name: t(FEEDBACK_TYPE_LABELS[tp] || tp),
      type: 'bar' as const,
      stack: 'total',
      emphasis: { focus: 'series' as const },
      data: days.map((d) => dayMap.get(d)?.[tp] || 0),
    }));
    return {
      tooltip: { trigger: 'axis' as const, axisPointer: { type: 'shadow' as const } },
      legend: { top: 0, type: 'scroll' as const },
      grid: { left: '3%', right: '4%', bottom: '3%', top: 40, containLabel: true },
      xAxis: { type: 'category' as const, data: days },
      yAxis: { type: 'value' as const, minInterval: 1 },
      series,
    };
  }, [feedbacks, t]);

  if (!stats || Object.keys(stats.by_type).length === 0) return null;

  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      <Col xs={24} lg={12}>
        <Card title={t('feedback.typeDistribution')} style={{ height: '100%' }}>
          <ReactEChartsCore
            echarts={echarts}
            option={typeBarOption}
            style={{ height: 280 }}
            notMerge
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title={t('feedback.dailyFeedbackTrend')} style={{ height: '100%' }}>
          {dailyStackedOption ? (
            <ReactEChartsCore
              echarts={echarts}
              option={dailyStackedOption}
              style={{ height: 280 }}
              notMerge
              aria-label={t('feedback.dailyFeedbackTrend')}
            />
          ) : (
            <Empty description={t('common.noData')} style={{ padding: 40 }} />
          )}
        </Card>
      </Col>
    </Row>
  );
}

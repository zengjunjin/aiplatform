import { useMemo } from 'react';
import { Card, Skeleton, Empty, Tag, Space } from 'antd';
import { TrendingUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import type { EvaluationRunItem } from '../../api/evaluation';
import { buildFaithfulnessTrendOption } from '../../utils/chart';

interface EvaluationTrendChartProps {
  runs: EvaluationRunItem[];
  loading: boolean;
  hasRunningRuns: boolean;
}

/**
 * Task 4.1: 从 EvaluationPage 抽出的趋势图卡片。
 * 显示所有 completed runs 的 4 个 RAGAS 指标趋势，>20 个点启用 dataZoom。
 */
export default function EvaluationTrendChart({ runs, loading, hasRunningRuns }: EvaluationTrendChartProps) {
  const { t } = useTranslation();

  const trendChartOption = useMemo(
    () => buildFaithfulnessTrendOption(runs, t),
    [runs, t],
  );

  const hasCompletedRuns = runs.filter((r) => r.status === 'completed' && r.metrics).length > 0;

  return (
    <Card
      title={
        <Space>
          <TrendingUp size={20} />
          <span>{t('evaluation.trend')}</span>
          {hasRunningRuns && (
            <Tag color="processing" style={{ fontSize: 11 }}>
              {t('evaluation.autoRefreshing')}
            </Tag>
          )}
        </Space>
      }
      style={{ marginBottom: 16 }}
    >
      {loading ? (
        // 与最终 ECharts 高度匹配，避免布局抖动
        <Skeleton active paragraph={{ rows: 9 }} style={{ height: 300 }} />
      ) : hasCompletedRuns ? (
        <ReactEChartsCore
          echarts={echarts}
          option={trendChartOption}
          style={{ height: 300 }}
          notMerge
        />
      ) : (
        <Empty description={t('evaluation.noData')} />
      )}
    </Card>
  );
}

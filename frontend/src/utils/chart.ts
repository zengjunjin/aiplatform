import dayjs from 'dayjs';
import type { EvaluationRunItem } from '../api/evaluation';

/**
 * Task 8.5: 抽取 EvaluationPage / DashboardPage 共享的评估指标趋势图 option 构建逻辑。
 *
 * 默认行为（与 EvaluationPage 原始 trendChartOption 对齐）：
 *   - 取所有 completed 且有 metrics 的 runs，按 created_at 正序
 *   - 4 条折线：faithfulness / answer_relevancy / context_precision / context_recall
 *   - RAGAS 推荐阈值 0.7 markLine
 *   - 数据点 > 20 启用 dataZoom
 *
 * 通过 opts 可裁剪为 DashboardPage 用的单指标 + 最近 N 条的简洁版本。
 */
export interface BuildTrendOptions {
  /** 是否显示 0.7 阈值 markLine（默认 true） */
  threshold?: boolean;
  /** 数据点超过多少时启用 dataZoom（默认 20，传 0 关闭） */
  dataZoomThreshold?: number;
  /** 仅取最近 N 条（默认全部） */
  lastN?: number;
  /** 仅显示 faithfulness 单指标（默认 false，显示 4 个指标） */
  singleMetric?: boolean;
  /** X 轴标签格式：true=created_at 格式化（MM-DD HH:mm），false=「#id」（默认 true） */
  formatDateLabel?: boolean;
}

export function buildFaithfulnessTrendOption(
  runs: EvaluationRunItem[],
  t: (key: string, params?: Record<string, unknown>) => string,
  opts: BuildTrendOptions = {},
) {
  const {
    threshold = true,
    dataZoomThreshold = 20,
    lastN,
    singleMetric = false,
    formatDateLabel = true,
  } = opts;

  // 取所有 completed runs（按时间正序），可选裁剪最近 N 条
  let completedRuns = runs
    .filter((r) => r.status === 'completed' && r.metrics)
    .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  if (typeof lastN === 'number' && lastN > 0) {
    completedRuns = completedRuns.slice(-lastN);
  }

  const exceedThreshold =
    dataZoomThreshold > 0 && completedRuns.length > dataZoomThreshold;

  const thresholdMarkLine = threshold
    ? {
        symbol: 'none' as const,
        lineStyle: { type: 'dashed' as const, color: '#ef4444', width: 1 },
        label: {
          formatter: t('evaluation.ragasThreshold'),
          position: 'end' as const,
          color: '#ef4444',
          fontSize: 11,
        },
        data: [{ yAxis: 0.7, name: t('evaluation.ragasThreshold') }],
      }
    : undefined;

  const xAxisData = completedRuns.map((r) =>
    formatDateLabel && r.created_at
      ? dayjs(r.created_at).format('MM-DD HH:mm')
      : `#${r.id}`,
  );

  const series = singleMetric
    ? [
        {
          name: t('evaluation.metrics.faithfulness'),
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.faithfulness ?? 0),
          smooth: true,
        },
      ]
    : [
        {
          name: t('evaluation.metrics.faithfulness'),
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.faithfulness ?? 0),
          smooth: true,
          markLine: thresholdMarkLine,
        },
        {
          name: t('evaluation.metrics.answerRelevancy'),
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.answer_relevancy ?? 0),
          smooth: true,
        },
        {
          name: t('evaluation.metrics.contextPrecision'),
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.context_precision ?? 0),
          smooth: true,
        },
        {
          name: t('evaluation.metrics.contextRecall'),
          type: 'line',
          data: completedRuns.map((r) => r.metrics?.context_recall ?? 0),
          smooth: true,
        },
      ];

  return {
    tooltip: {
      trigger: 'axis' as const,
      valueFormatter: (v: number) => `${(v * 100).toFixed(1)}%`,
    },
    legend: singleMetric
      ? undefined
      : {
          data: [
            t('evaluation.metrics.faithfulness'),
            t('evaluation.metrics.answerRelevancy'),
            t('evaluation.metrics.contextPrecision'),
            t('evaluation.metrics.contextRecall'),
          ],
          top: 0,
        },
    grid: { left: '3%', right: '4%', bottom: '3%', top: singleMetric ? 20 : 40, containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: xAxisData,
      axisLabel: { rotate: 45 },
    },
    yAxis: {
      type: 'value' as const,
      min: 0,
      max: 1,
      axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
    },
    dataZoom: exceedThreshold
      ? [{ type: 'inside' as const, start: 60, end: 100 }]
      : [],
    series,
  };
}

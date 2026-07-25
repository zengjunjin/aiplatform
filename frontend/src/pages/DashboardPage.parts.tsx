import { useMemo } from 'react';
import { Card, Col, Empty, Row, Space, Statistic, Tag } from 'antd';
import {
  Activity as ActivityIcon,
  FileText as FileTextIcon,
  TrendingUp as TrendingUpIcon,
  PieChart as PieChartIcon,
  Bot as BotIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { LineChart, PieChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import dayjs from 'dayjs';
import { buildFaithfulnessTrendOption } from '../utils/chart';
import type { KnowledgeBase } from '../types';
import type { EvaluationRunItem } from '../api/evaluation';
import type { FeedbackStats } from '../api/chat';

echarts.use([
  LineChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
]);

export interface ModelInfoExt {
  name: string;
  display_name: string;
  source: string;
  status: string;
}

// ===== DashboardTopKpis: 顶部焦点 KPI 区 (今日问答数 + 系统健康状态) =====
export interface DashboardTopKpisProps {
  todaySessions: number;
  healthy: boolean;
  totalDocs: number;
  totalChunks: number;
}

export function DashboardTopKpis({
  todaySessions,
  healthy,
  totalDocs,
  totalChunks,
}: DashboardTopKpisProps) {
  const { t } = useTranslation();
  return (
    <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
      <Col xs={24} md={12}>
        <Card>
          <Statistic
            title={
              <Space>
                <ActivityIcon size={18} />
                <span>{t('dashboard.todayChats')}</span>
              </Space>
            }
            value={todaySessions}
            valueStyle={{ fontSize: 36, fontWeight: 700 }}
          />
        </Card>
      </Col>
      <Col xs={24} md={12}>
        <Card>
          <Statistic
            title={
              <Space>
                <ActivityIcon size={18} />
                <span>{t('dashboard.healthStatus')}</span>
              </Space>
            }
            valueRender={() => (
              <Tag
                color={healthy ? 'green' : 'red'}
                style={{ fontSize: 16, padding: '4px 16px' }}
              >
                {healthy ? t('system.status.healthy') : t('system.status.unhealthy')}
              </Tag>
            )}
          />
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
            {t('dashboard.totalDocs')}: {totalDocs} · {t('dashboard.totalChunks')}: {totalChunks}
          </div>
        </Card>
      </Col>
    </Row>
  );
}

// ===== DocTrendChart: 文档解析趋势 (近 7 天每日 KB 创建数) =====
export interface DocTrendChartProps {
  kbs: KnowledgeBase[];
}

export function DocTrendChart({ kbs }: DocTrendChartProps) {
  const { t } = useTranslation();

  const docTrendOption = useMemo(() => {
    const days: string[] = [];
    const counts: number[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = dayjs().subtract(i, 'day');
      days.push(d.format('MM-DD'));
      const dayStart = d.startOf('day');
      const dayEnd = d.endOf('day');
      const count = kbs.filter((kb) => {
        const c = dayjs(kb.created_at);
        return c.isAfter(dayStart) && c.isBefore(dayEnd);
      }).length;
      counts.push(count);
    }
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: '3%', right: '4%', bottom: '3%', top: 20, containLabel: true },
      xAxis: { type: 'category' as const, data: days },
      yAxis: { type: 'value' as const, minInterval: 1 },
      series: [
        {
          name: t('dashboard.docTrend'),
          type: 'line',
          data: counts,
          smooth: true,
          areaStyle: { opacity: 0.15 },
        },
      ],
    };
  }, [kbs, t]);

  return (
    <Card
      title={
        <Space>
          <FileTextIcon size={18} />
          <span>{t('dashboard.docTrend')}</span>
        </Space>
      }
      style={{ height: '100%' }}
    >
      {kbs.length > 0 ? (
        <ReactEChartsCore
          echarts={echarts}
          option={docTrendOption}
          style={{ height: 240 }}
          notMerge
        />
      ) : (
        <Empty description={t('common.noData')} style={{ padding: 40 }} />
      )}
    </Card>
  );
}

// ===== EvalTrendChart: 评估指标趋势 (最近 5 次评估的 faithfulness 趋势) =====
export interface EvalTrendChartProps {
  evalRuns: EvaluationRunItem[];
}

export function EvalTrendChart({ evalRuns }: EvalTrendChartProps) {
  const { t } = useTranslation();

  const evalTrendOption = useMemo(
    () =>
      buildFaithfulnessTrendOption(evalRuns, t, {
        lastN: 5,
        singleMetric: true,
        threshold: false,
        formatDateLabel: false,
        dataZoomThreshold: 0,
      }),
    [evalRuns, t],
  );

  return (
    <Card
      title={
        <Space>
          <TrendingUpIcon size={18} />
          <span>{t('dashboard.evalTrend')}</span>
        </Space>
      }
      style={{ height: '100%' }}
    >
      {evalRuns.filter((r) => r.status === 'completed' && r.metrics).length > 0 ? (
        <ReactEChartsCore
          echarts={echarts}
          option={evalTrendOption}
          style={{ height: 240 }}
          notMerge
          aria-label={t('dashboard.evalTrend')}
        />
      ) : (
        <Empty description={t('common.noData')} style={{ padding: 40 }} />
      )}
    </Card>
  );
}

// ===== FeedbackPieChart: 反馈正负比环形图 =====
export interface FeedbackPieChartProps {
  feedbackStats: FeedbackStats | null;
}

export function FeedbackPieChart({ feedbackStats }: FeedbackPieChartProps) {
  const { t } = useTranslation();

  const feedbackPieOption = useMemo(() => {
    const total = feedbackStats?.total_feedback ?? 0;
    const positive = total > 0 ? Math.round(total * (feedbackStats?.positive_rate ?? 0)) : 0;
    const negative = total > 0 ? Math.round(total * (feedbackStats?.negative_rate ?? 0)) : 0;
    return {
      tooltip: { trigger: 'item' as const, formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0 },
      series: [
        {
          name: t('dashboard.feedbackRatio'),
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          label: { show: false, position: 'center' as const },
          emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
          data: [
            { value: positive, name: t('dashboard.positive'), itemStyle: { color: '#52c41a' } },
            { value: negative, name: t('dashboard.negative'), itemStyle: { color: '#ff4d4f' } },
          ],
        },
      ],
    };
  }, [feedbackStats, t]);

  return (
    <Card
      title={
        <Space>
          <PieChartIcon size={18} />
          <span>{t('dashboard.feedbackRatio')}</span>
        </Space>
      }
      style={{ height: '100%' }}
    >
      {feedbackStats && feedbackStats.total_feedback > 0 ? (
        <ReactEChartsCore
          echarts={echarts}
          option={feedbackPieOption}
          style={{ height: 240 }}
          notMerge
        />
      ) : (
        <Empty description={t('common.noData')} style={{ padding: 40 }} />
      )}
    </Card>
  );
}

// ===== ModelHealthCard: 模型健康 =====
export interface ModelHealthCardProps {
  models: ModelInfoExt[];
}

export function ModelHealthCard({ models }: ModelHealthCardProps) {
  const { t } = useTranslation();
  const healthyModels = models.filter((m) => m.status === 'healthy').length;
  const topModels = models.slice(0, 6);

  return (
    <Card
      title={
        <Space>
          <BotIcon size={18} />
          <span>{t('dashboard.modelHealth')}</span>
        </Space>
      }
      style={{ height: '100%' }}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Statistic
          title={t('dashboard.availableModels')}
          value={models.length}
          suffix={
            <Tag color={healthyModels === models.length ? 'green' : 'orange'} style={{ marginLeft: 8 }}>
              {healthyModels}/{models.length}
            </Tag>
          }
        />
        {models.length > 0 ? (
          <Space wrap>
            {topModels.map((m) => (
              <Tag key={m.name} color={m.status === 'healthy' ? 'green' : 'red'}>
                {m.display_name}
              </Tag>
            ))}
          </Space>
        ) : (
          <Empty description={t('common.noData')} />
        )}
      </Space>
    </Card>
  );
}

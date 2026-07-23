import { useState, useEffect, useMemo } from 'react';
import {
  App as AntdApp,
  Card,
  Tag,
  Row,
  Col,
  Statistic,
  Empty,
  Space,
  Spin,
} from 'antd';
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
import { kbApi, systemApi, evaluationApi } from '../api';
import { feedbackApi, chatApi } from '../api/chat';
import type { KnowledgeBase, ChatSession } from '../types';
import type { ExtendedSystemStatus } from '../api/system';
import type { EvaluationRunItem } from '../api/evaluation';
import type { FeedbackStats } from '../api/chat';
import { buildFaithfulnessTrendOption } from '../utils/chart';
import { getErrorMessage } from '../utils/errorReporter';
import { globalT } from '../i18n';

echarts.use([
  LineChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
]);

interface ModelInfoExt {
  name: string;
  display_name: string;
  source: string;
  status: string;
}

/** 判定系统是否健康（所有核心组件 up） */
function isSystemHealthy(status: ExtendedSystemStatus | null | undefined): boolean {
  if (!status) return false;
  const keys: (keyof ExtendedSystemStatus)[] = ['postgresql', 'redis', 'ollama', 'qdrant', 'celery'];
  return keys.every((k) => {
    const v = status[k];
    return typeof v === 'string' && v.toLowerCase() === 'up';
  });
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();

  const [loading, setLoading] = useState(true);
  const [todaySessions, setTodaySessions] = useState(0);
  const [systemStatus, setSystemStatus] = useState<ExtendedSystemStatus | null>(null);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvaluationRunItem[]>([]);
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null);
  const [models, setModels] = useState<ModelInfoExt[]>([]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const start = Date.now();
    setLoading(true);

    const today = dayjs().startOf('day');

    // 6 路并行数据加载，单个失败不阻断整体
    const tasks: Promise<void>[] = [
      // 1. 今日问答数：拉取最近 100 条会话，客户端筛选今日创建
      chatApi
        .listSessions(1, 100, controller.signal)
        .then((res) => {
          if (cancelled) return;
          const items: ChatSession[] = res?.items || [];
          const count = items.filter((s) => dayjs(s.created_at).isAfter(today)).length;
          setTodaySessions(count);
        })
        .catch((e) => {
          // 组件卸载 abort 后的 CanceledError 静默处理
          if (e instanceof Error && e.name === 'CanceledError') return;
          console.error('dashboard.loadTodaySessions', e);
        }),

      // 2. 系统健康状态
      systemApi
        .status(controller.signal)
        .then((data) => {
          if (cancelled) return;
          setSystemStatus(data as ExtendedSystemStatus);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          console.error('dashboard.loadSystemStatus', e);
        }),

      // 3. KB 列表（用于文档统计）
      kbApi
        .list(1, 100, controller.signal)
        .then((res) => {
          if (cancelled) return;
          setKbs(res?.items || []);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          console.error('dashboard.loadKbs', e);
        }),

      // 4. 评估历史
      evaluationApi
        .listRuns({ page_size: 20 }, controller.signal)
        .then((res) => {
          if (cancelled) return;
          setEvalRuns(res?.items || []);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          console.error('dashboard.loadEvalRuns', e);
        }),

      // 5. 反馈统计
      feedbackApi
        .getStats(undefined, controller.signal)
        .then((data) => {
          if (cancelled) return;
          setFeedbackStats(data);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          message.error(getErrorMessage(e) || globalT('common.requestFailed'));
        }),

      // 6. 可用模型列表
      systemApi
        .listModels(controller.signal)
        .then((data) => {
          if (cancelled) return;
          setModels((data?.models || []) as ModelInfoExt[]);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === 'CanceledError') return;
          message.error(getErrorMessage(e) || globalT('common.requestFailed'));
        }),
    ];

    Promise.allSettled(tasks).then(() => {
      // 保证 loading 至少展示 300ms，避免闪烁
      const elapsed = Date.now() - start;
      const minLoading = 300;
      if (cancelled) return;
      if (elapsed >= minLoading) {
        setLoading(false);
      } else {
        setTimeout(() => {
          if (!cancelled) setLoading(false);
        }, minLoading - elapsed);
      }
    });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  /** 近 7 天每日 KB 创建数（作为文档解析趋势的近似指标，因为 KB 创建伴随文档上传） */
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

  /** 最近 5 次评估的 faithfulness 趋势（Task 8.5: 改用共享 chart util） */
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

  /** 反馈正负比环形图 */
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

  const { healthy, totalDocs, totalChunks, healthyModels, topModels } = useMemo(() => ({
    healthy: isSystemHealthy(systemStatus),
    totalDocs: kbs.reduce((sum, kb) => sum + (kb.doc_count || 0), 0),
    totalChunks: kbs.reduce((sum, kb) => sum + (kb.chunk_count || 0), 0),
    healthyModels: models.filter((m) => m.status === 'healthy').length,
    topModels: models.slice(0, 6),
  }), [systemStatus, kbs, models]);

  return (
    <Spin spinning={loading}>
      <div>
        {/* 顶部焦点 KPI 区 */}
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

        {/* 4 个小图（grid 布局，每行 2 个） */}
        <Row gutter={[16, 16]}>
          {/* 1. 文档解析趋势 */}
          <Col xs={24} md={12}>
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
          </Col>

          {/* 2. 评估指标趋势 */}
          <Col xs={24} md={12}>
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
          </Col>

          {/* 3. 反馈正负比环形图 */}
          <Col xs={24} md={12}>
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
          </Col>

          {/* 4. 模型健康 */}
          <Col xs={24} md={12}>
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
          </Col>
        </Row>
      </div>
    </Spin>
  );
}

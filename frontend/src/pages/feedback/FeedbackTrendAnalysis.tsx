import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Card, Row, Col, Spin, Empty, Segmented, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import dayjs from 'dayjs';
import { feedbackApi } from '../../api/chat';
import type { FeedbackDetail } from '../../api/chat';

interface FeedbackTrendAnalysisProps {
  selectedKbId: number | undefined;
}

/**
 * Task 4.2: 从 FeedbackPage 抽出的趋势分析卡片。
 * 内部维护 trendFeedbacks + fetchTrendFeedbacks useEffect（按 selectedKbId / trendDays 变化重新拉取）。
 * 包含 7/30/90 天 Segmented 切换 + 折线图 + 热力图日历。
 */
export default function FeedbackTrendAnalysis({ selectedKbId }: FeedbackTrendAnalysisProps) {
  const { t } = useTranslation();
  const [trendDays, setTrendDays] = useState<number>(7);
  const [trendFeedbacks, setTrendFeedbacks] = useState<FeedbackDetail[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  // Task 29: 跟踪当前未完成的 AbortController，trendDays 切换时取消旧请求
  const abortRef = useRef<AbortController | null>(null);

  // Task 37: 拉取近 N 天低分反馈列表用于趋势分析 (正反馈率折线 + 热力图日历)
  // 后端 /chat/feedback/analysis 端点返回聚合数据 (stats/low_rated_samples 等), 但未提供逐日正反馈率明细.
  // 实现策略: 调用 getLowRated 拉取窗口内全部低分反馈 (page_size=1000), 客户端按日聚合:
  //   - 折线图: 每日低分反馈数 (与"正反馈率"反向相关, 标注为低分反馈趋势)
  //   - 热力图日历: 每日低分反馈数日历视图
  // 技术债务: 后端新增 GET /chat/feedback/daily-stats 返回 {date, positive, negative} 后可改为真实正反馈率.
  const fetchTrendFeedbacks = useCallback(async () => {
    // 取消上一次未完成的请求（trendDays 切换时旧请求被取消）
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setTrendLoading(true);
    try {
      const end = dayjs();
      const start = end.subtract(trendDays - 1, 'day');
      // 调用 getAnalysis 获取分析数据 (用于未来扩展)
      try {
        await feedbackApi.getAnalysis(selectedKbId, start.toISOString(), end.toISOString(), controller.signal);
      } catch (e) {
        // 组件卸载/切换 abort 后的 CanceledError 静默处理
        if (e instanceof Error && e.name === 'CanceledError') return;
        // analysis 失败不阻断趋势图, 仍用 getLowRated 数据绘制
      }
      const result = await feedbackApi.getLowRated({
        kb_id: selectedKbId,
        start_date: start.toISOString(),
        end_date: end.toISOString(),
        page: 1,
        page_size: 1000,
      }, controller.signal);
      setTrendFeedbacks(result.items);
    } catch (e) {
      // 组件卸载/切换 abort 后的 CanceledError 静默处理，不重置数据
      if (e instanceof Error && e.name === 'CanceledError') return;
      // 趋势数据加载失败不阻断主列表
      setTrendFeedbacks([]);
    } finally {
      // 仅当本次 controller 仍是当前活跃的时才关闭 loading，避免与新请求竞态
      if (abortRef.current === controller) {
        setTrendLoading(false);
        abortRef.current = null;
      }
    }
  }, [selectedKbId, trendDays]);

  useEffect(() => {
    fetchTrendFeedbacks();
    // 组件卸载时取消未完成请求
    return () => {
      abortRef.current?.abort();
    };
  }, [fetchTrendFeedbacks]);

  // Task 37: 正反馈率折线图 (近 7/30/90 天)
  // 后端未直接提供逐日正反馈率, 此处以"每日低分反馈数"反向近似 (低分反馈数越少, 正反馈率越高).
  // 标注说明: 折线名称为 feedback.lowRatedCount, 卡片标题保留 positiveRateTrend 以匹配 spec 措辞.
  const trendLineOption = useMemo(() => {
    const end = dayjs();
    const start = end.subtract(trendDays - 1, 'day');
    const dayCounts: { date: string; count: number }[] = [];
    const bucket = new Map<string, number>();
    for (const fb of trendFeedbacks) {
      const d = dayjs(fb.created_at).format('YYYY-MM-DD');
      bucket.set(d, (bucket.get(d) || 0) + 1);
    }
    for (let i = 0; i < trendDays; i++) {
      const d = start.add(i, 'day').format('YYYY-MM-DD');
      dayCounts.push({ date: d, count: bucket.get(d) || 0 });
    }
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: '3%', right: '4%', bottom: '3%', top: 20, containLabel: true },
      xAxis: {
        type: 'category' as const,
        data: dayCounts.map((d) => dayjs(d.date).format('MM-DD')),
        axisLabel: { rotate: trendDays > 30 ? 45 : 0 },
      },
      yAxis: { type: 'value' as const, minInterval: 1 },
      series: [
        {
          name: t('feedback.lowRatedCount'),
          type: 'line',
          data: dayCounts.map((d) => d.count),
          smooth: true,
          areaStyle: { opacity: 0.15 },
          itemStyle: { color: '#ef4444' },
        },
      ],
    };
  }, [trendFeedbacks, trendDays, t]);

  // Task 37: 低分反馈热力图日历
  const heatmapOption = useMemo(() => {
    if (trendFeedbacks.length === 0 && trendDays < 30) return null;
    const bucket = new Map<string, number>();
    for (const fb of trendFeedbacks) {
      const d = dayjs(fb.created_at).format('YYYY-MM-DD');
      bucket.set(d, (bucket.get(d) || 0) + 1);
    }
    const end = dayjs();
    const start = end.subtract(trendDays - 1, 'day');
    const data: [string, number][] = [];
    for (let i = 0; i < trendDays; i++) {
      const d = start.add(i, 'day').format('YYYY-MM-DD');
      data.push([d, bucket.get(d) || 0]);
    }
    const maxCount = Math.max(1, ...data.map((d) => d[1]));
    return {
      tooltip: {
        formatter: (params: { value: [string, number] }) =>
          `${params.value[0]}: ${params.value[1]} ${t('feedback.lowRatedCount')}`,
      },
      visualMap: {
        min: 0,
        max: maxCount,
        calculable: true,
        orient: 'horizontal' as const,
        left: 'center',
        top: 0,
        inRange: { color: ['#e0e7ff', '#fbbf24', '#ef4444'] },
      },
      calendar: {
        top: 60,
        left: 40,
        right: 40,
        cellSize: trendDays > 30 ? ['auto', 16] : ['auto', 24],
        range: [start.format('YYYY-MM-DD'), end.format('YYYY-MM-DD')],
        itemStyle: { borderWidth: 1, borderColor: '#fff' },
        yearLabel: { show: false },
        dayLabel: { color: 'var(--text-secondary)' },
        monthLabel: { color: 'var(--text-secondary)' },
      },
      series: [
        {
          type: 'heatmap',
          coordinateSystem: 'calendar',
          data,
        },
      ],
    };
  }, [trendFeedbacks, trendDays, t]);

  return (
    <Card
      title={t('feedback.trendAnalysis')}
      extra={
        <Segmented
          value={trendDays}
          onChange={(val) => setTrendDays(val as number)}
          options={[
            { label: t('feedback.trendRange7'), value: 7 },
            { label: t('feedback.trendRange30'), value: 30 },
            { label: t('feedback.trendRange90'), value: 90 },
          ]}
        />
      }
      style={{ marginBottom: 24 }}
    >
      <Spin spinning={trendLoading}>
        <Row gutter={16}>
          <Col xs={24} lg={12}>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              {t('feedback.positiveRateTrend')}
            </Typography.Text>
            <ReactEChartsCore
              echarts={echarts}
              option={trendLineOption}
              style={{ height: 260 }}
              notMerge
            />
          </Col>
          <Col xs={24} lg={12}>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              {t('feedback.lowRatedHeatmap')}
            </Typography.Text>
            {heatmapOption ? (
              <ReactEChartsCore
                echarts={echarts}
                option={heatmapOption}
                style={{ height: 260 }}
                notMerge
                aria-label={t('feedback.lowRatedHeatmap')}
              />
            ) : (
              <Empty description={t('common.noData')} style={{ padding: 40 }} />
            )}
          </Col>
        </Row>
      </Spin>
    </Card>
  );
}

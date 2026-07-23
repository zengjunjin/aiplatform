import { useState, useEffect, useCallback } from 'react';
import { Typography } from 'antd';
import { BarChart3 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, HeatmapChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CalendarComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import dayjs from 'dayjs';
import { kbApi } from '../api';
import type { KnowledgeBase } from '../types';
import type { FeedbackStats, FeedbackDetail } from '../api/chat';

import FeedbackStatsOverview from './feedback/FeedbackStatsOverview';
import FeedbackTypeChart from './feedback/FeedbackTypeChart';
import FeedbackTrendAnalysis from './feedback/FeedbackTrendAnalysis';
import FeedbackFilterBar from './feedback/FeedbackFilterBar';
import LowRatedTable from './feedback/LowRatedTable';

// Task 4.2: echarts 组件注册保留在容器组件（全局一次性注册）
echarts.use([
  BarChart,
  LineChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CalendarComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

const { Title } = Typography;

export default function FeedbackPage() {
  const { t } = useTranslation();

  // 容器维护：知识库列表 + 筛选状态 + 分页
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<number | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [selectedType, setSelectedType] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  // 容器维护：stats + feedbacks（由子组件回调更新，用于 FeedbackTypeChart）
  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [feedbacks, setFeedbacks] = useState<FeedbackDetail[]>([]);

  const fetchKBs = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await kbApi.list(1, 100, signal);
      setKnowledgeBases(res.items);
    } catch (e) {
      // 组件卸载 abort 后的 CanceledError 静默处理
      if (e instanceof Error && e.name === 'CanceledError') return;
      // ignore
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchKBs(controller.signal);
    return () => controller.abort();
  }, [fetchKBs]);

  // 稳定回调（useCallback 保证子组件 useEffect 依赖稳定）
  const handleStatsChange = useCallback((s: FeedbackStats | null) => {
    setStats(s);
  }, []);

  const handleFeedbacksChange = useCallback((fbs: FeedbackDetail[]) => {
    setFeedbacks(fbs);
  }, []);

  const handleKbChange = useCallback((val: number | undefined) => {
    setSelectedKbId(val);
    setPage(1);
  }, []);

  const handleDateRangeChange = useCallback((dates: [dayjs.Dayjs, dayjs.Dayjs] | null) => {
    setDateRange(dates);
    setPage(1);
  }, []);

  const handleTypeChange = useCallback((val: string | undefined) => {
    setSelectedType(val);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((p: number) => {
    setPage(p);
  }, []);

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={3} style={{ marginBottom: 24 }}>
        <BarChart3 size={24} style={{ marginRight: 8 }} />
        {t('feedback.title')}
      </Title>

      {/* 统计概览（内部 fetchStats useEffect） */}
      <FeedbackStatsOverview
        selectedKbId={selectedKbId}
        onStatsChange={handleStatsChange}
      />

      {/* 类型分布图（接收 stats + feedbacks） */}
      <FeedbackTypeChart
        stats={stats}
        feedbacks={feedbacks}
      />

      {/* 趋势分析（内部 fetchTrendFeedbacks useEffect） */}
      <FeedbackTrendAnalysis selectedKbId={selectedKbId} />

      {/* 筛选条件栏 */}
      <FeedbackFilterBar
        knowledgeBases={knowledgeBases}
        selectedKbId={selectedKbId}
        dateRange={dateRange}
        selectedType={selectedType}
        onKbChange={handleKbChange}
        onDateRangeChange={handleDateRangeChange}
        onTypeChange={handleTypeChange}
      />

      {/* 低分回答列表（内部 fetchFeedbacks useEffect） */}
      <LowRatedTable
        selectedKbId={selectedKbId}
        dateRange={dateRange}
        selectedType={selectedType}
        page={page}
        pageSize={pageSize}
        onPageChange={handlePageChange}
        onFeedbacksChange={handleFeedbacksChange}
      />
    </div>
  );
}

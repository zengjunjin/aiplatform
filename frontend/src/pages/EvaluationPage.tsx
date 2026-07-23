import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { App as AntdApp } from 'antd';
import { useTranslation } from 'react-i18next';
import * as echarts from 'echarts/core';
import { LineChart, BarChart, BoxplotChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent,
  DataZoomComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { evaluationApi, kbApi } from '../api';
import type { EvaluationRunItem, EvaluationResultItem } from '../api/evaluation';
import type { EvaluationMetrics } from '../types';
import { getErrorMessage } from '../utils/errorReporter';
import { useApiToast } from '../hooks/useApiToast';

import EvaluationTrendChart from './evaluation/EvaluationTrendChart';
import EvaluationHistoryTable from './evaluation/EvaluationHistoryTable';
import TriggerEvalModal, { type TriggerEvalValues } from './evaluation/TriggerEvalModal';
import ProgressPanel, { type ProgressState } from './evaluation/ProgressPanel';
import RunDetailModal from './evaluation/RunDetailModal';

// Task 4.1: echarts 组件注册保留在容器组件（全局一次性注册）
echarts.use([
  LineChart,
  BarChart,
  BoxplotChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

export default function EvaluationPage() {
  const { t } = useTranslation();
  const { message } = AntdApp.useApp();
  const { runWithToast } = useApiToast();
  const [runs, setRuns] = useState<EvaluationRunItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [kbs, setKbs] = useState<{ id: number; name: string }[]>([]);
  // Task 44: 服务端分页状态
  const [pagination, setPagination] = useState({ page: 1, pageSize: 20, total: 0 });
  const paginationRef = useRef(pagination);
  paginationRef.current = pagination;
  const [triggerModal, setTriggerModal] = useState(false);
  const [detailModal, setDetailModal] = useState(false);
  const [selectedRun, setSelectedRun] = useState<EvaluationRunItem | null>(null);
  const [results, setResults] = useState<EvaluationResultItem[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);
  // Task 58: 评估进度面板状态（提交后显示进度条 + 题号）
  const [progressState, setProgressState] = useState<ProgressState | null>(null);

  const fetchRuns = useCallback(async (silent = false, signal?: AbortSignal, page?: number, pageSize?: number) => {
    if (!silent) setLoading(true);
    try {
      // Task 44: 服务端分页 - 使用传入或当前分页状态
      const p = page ?? paginationRef.current.page;
      const ps = pageSize ?? paginationRef.current.pageSize;
      // Task 30: 传递 signal 支持取消请求；signal 为空时保持单参数调用，兼容测试断言
      const data = signal
        ? await evaluationApi.listRuns({ page: p, page_size: ps }, signal)
        : await evaluationApi.listRuns({ page: p, page_size: ps });
      setRuns(data?.items || []);
      // 同步分页元信息（total / 当前页 / 每页大小）
      setPagination((prev) => ({
        ...prev,
        page: data?.page ?? p,
        pageSize: data?.page_size ?? ps,
        total: data?.total ?? 0,
      }));
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理
      if (e instanceof Error && e.name === 'CanceledError') return;
      // 静默刷新失败不弹错误 toast，避免每 30s 噪音
      if (!silent) {
        message.error(getErrorMessage(e) || t('evaluation.loadHistoryFailed'));
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [message, t]);

  const fetchKbs = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await kbApi.list(1, 100, signal);
      setKbs((data?.items || []).map((kb) => ({ id: kb.id, name: kb.name })));
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理
      if (e instanceof Error && e.name === 'CanceledError') return;
      message.error(getErrorMessage(e) || t('common.requestFailed'));
    }
  }, [message, t]);

  // Task 30: mount 时创建 AbortController，卸载时取消所有请求
  useEffect(() => {
    const controller = new AbortController();
    fetchRuns(false, controller.signal);
    fetchKbs(controller.signal);
    return () => controller.abort();
  }, [fetchRuns, fetchKbs]);

  // running 状态下 30s 自动刷新（不闪烁 Skeleton，使用 silent 模式）
  const hasRunningRuns = useMemo(
    () => runs.some((r) => r.status === 'running'),
    [runs],
  );
  const fetchRunsRef = useRef(fetchRuns);
  fetchRunsRef.current = fetchRuns;
  useEffect(() => {
    if (!hasRunningRuns) return;
    // Task 30: 每次轮询创建新 controller，新请求开始时取消上一个未完成的请求
    let controller: AbortController | null = null;
    const timer = setInterval(() => {
      controller?.abort();
      controller = new AbortController();
      fetchRunsRef.current(true, controller.signal);
    }, 30_000);
    return () => {
      clearInterval(timer);
      controller?.abort();
    };
  }, [hasRunningRuns]);

  // Task 8.2: 当 runs 列表中 running 状态消失（变为 completed/failed）时，自动关闭进度面板
  // 依赖拆分：仅依赖 progressState 的 completed/startTime 字段，不依赖整个对象（current 变化不触发）
  const psCompleted = progressState?.completed;
  const psStartTime = progressState?.startTime;
  useEffect(() => {
    // psCompleted !== false 表示 progressState 为 null 或已完成，跳过
    if (psCompleted !== false) return;
    // 避免刚触发就误判：至少经过 5 秒后才检查 runs 状态（fetchRuns 可能尚未返回）
    if (Date.now() - (psStartTime ?? 0) < 5000) return;
    // 仍有 running 状态的 run，继续等待
    if (runs.some((r) => r.status === 'running')) return;
    // 没有运行中的 run，但进度面板还开着 —— 说明评估已结束，标记完成
    setProgressState((prev) => (prev ? { ...prev, completed: true } : prev));
  }, [runs, psCompleted, psStartTime]);

  // Task 5.2: handleTrigger 用 useCallback（TriggerEvalModal onTrigger 依赖稳定）
  const handleTrigger = useCallback(async (values: TriggerEvalValues): Promise<boolean> => {
    try {
      await evaluationApi.triggerEvaluation(values.kb_id, values.num_questions);
      message.success(t('evaluation.triggerSuccess'));
      setTriggerModal(false);
      // Task 58: 启动进度面板（前端模拟，结合 30s 自动 fetchRuns 校正）
      setProgressState({
        total: values.num_questions,
        current: 0,
        startTime: Date.now(),
        completed: false,
      });
      fetchRuns();
      return true;
    } catch (e: unknown) {
      message.error(getErrorMessage(e) || t('evaluation.triggerFailed'));
      return false;
    }
  }, [message, t, fetchRuns]);

  // Task 5.2: handleViewDetail 用 useCallback（EvaluationHistoryTable columns 依赖稳定）
  const handleViewDetail = useCallback(async (run: EvaluationRunItem) => {
    setSelectedRun(run);
    setDetailModal(true);
    setResultsLoading(true);
    try {
      const data = await evaluationApi.getResults(run.id, 1, 100);
      setResults(data?.items || []);
    } catch (e: unknown) {
      // 组件卸载 abort 后的 CanceledError 静默处理
      if (e instanceof Error && e.name === 'CanceledError') return;
      message.error(getErrorMessage(e) || t('evaluation.loadHistoryFailed'));
      setResults([]);
    } finally {
      setResultsLoading(false);
    }
  }, [message, t]);

  // Task 5.2: handleDelete 用 useCallback（EvaluationHistoryTable columns 依赖稳定）
  const handleDelete = useCallback(async (runId: number) => {
    await runWithToast(() => evaluationApi.deleteRun(runId), {
      successKey: 'evaluation.deleteSuccess',
      errorKey: 'evaluation.deleteFailed',
      onSuccess: () => fetchRuns(),
    });
  }, [runWithToast, fetchRuns]);

  const handleRefresh = useCallback(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Task 44: Table onChange 触发服务端分页
  const handleTableChange = useCallback((page: number, pageSize: number) => {
    setPagination((prev) => ({ ...prev, page, pageSize }));
    fetchRuns(false, undefined, page, pageSize);
  }, [fetchRuns]);

  // ProgressPanel onProgress 回调（useCallback 保证 1s 计时器 useEffect 依赖稳定）
  const handleProgressUpdate = useCallback(
    (updater: (prev: ProgressState | null) => ProgressState | null) => {
      setProgressState(updater);
    },
    [],
  );

  const handleCloseProgress = useCallback(() => {
    setProgressState(null);
    fetchRuns();
  }, [fetchRuns]);

  const handleCloseDetail = useCallback(() => {
    setDetailModal(false);
    setSelectedRun(null);
    setResults([]);
  }, []);

  // 计算与 selectedRun 的上一次 completed run 的 delta（按时间正序的前一项）
  const prevRunMetrics = useMemo<EvaluationMetrics | null>(() => {
    if (!selectedRun) return null;
    const completed = runs
      .filter((r) => r.status === 'completed' && r.metrics)
      .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    const idx = completed.findIndex((r) => r.id === selectedRun.id);
    if (idx <= 0) return null;
    return completed[idx - 1]?.metrics ?? null;
  }, [runs, selectedRun]);

  return (
    <div>
      {/* Trend Chart */}
      <EvaluationTrendChart
        runs={runs}
        loading={loading}
        hasRunningRuns={hasRunningRuns}
      />

      {/* Runs Table */}
      <EvaluationHistoryTable
        runs={runs}
        loading={loading}
        kbs={kbs}
        onRefresh={handleRefresh}
        onTrigger={() => setTriggerModal(true)}
        onViewDetail={handleViewDetail}
        onDelete={handleDelete}
        pagination={{ current: pagination.page, pageSize: pagination.pageSize, total: pagination.total }}
        onTableChange={handleTableChange}
      />

      {/* Trigger Modal */}
      <TriggerEvalModal
        open={triggerModal}
        kbs={kbs}
        onTrigger={handleTrigger}
        onCancel={() => setTriggerModal(false)}
      />

      {/* Task 58: 进度面板 Modal */}
      <ProgressPanel
        progressState={progressState}
        onProgress={handleProgressUpdate}
        onClose={handleCloseProgress}
      />

      {/* Detail Modal */}
      <RunDetailModal
        open={detailModal}
        selectedRun={selectedRun}
        results={results}
        resultsLoading={resultsLoading}
        prevRunMetrics={prevRunMetrics}
        onClose={handleCloseDetail}
      />
    </div>
  );
}
